package com.smartlect.biz.impl;

import java.util.ArrayList;
import java.util.Date;
import java.util.List;

import com.smartlect.mq.RocketMqTopics;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.api.dto.PayOrderMessageDTO;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.api.enums.LogisticsStatusEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.entity.po.OrderLogisticsInfoRecord;
import com.smartlect.entity.query.OrderLogisticsInfoRecordQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.state.OrderStateEvent;
import com.smartlect.state.OrderStateMachine;
import com.smartlect.biz.OrderLogisticsInfoRecordService;
import com.smartlect.support.MqIdempotencyKeys;
import jakarta.annotation.Resource;

import org.springframework.stereotype.Service;

import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.query.OrderLogisticsInfoQuery;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.mappers.OrderLogisticsInfoMapper;
import com.smartlect.biz.OrderLogisticsInfoService;
import com.smartlect.utils.StringTools;
import org.springframework.transaction.annotation.Transactional;
import com.smartlect.utils.PageUtils;

@Service("orderLogisticsInfoService")
public class OrderLogisticsInfoServiceImpl implements OrderLogisticsInfoService {

	@Resource
	private OrderLogisticsInfoMapper<OrderLogisticsInfo, OrderLogisticsInfoQuery> orderLogisticsInfoMapper;

	@Resource
	private OrderLogisticsInfoRecordService orderLogisticsInfoRecordService;

	@Resource
	private OrderStateMachine orderStateMachine;

	@Resource
	private TransactionalMqSender transactionalMqSender;

	@Override
	public List<OrderLogisticsInfo> findListByParam(OrderLogisticsInfoQuery param) {
		return this.orderLogisticsInfoMapper.selectList(param);
	}

	@Override
	public Integer findCountByParam(OrderLogisticsInfoQuery param) {
		return this.orderLogisticsInfoMapper.selectCount(param);
	}

	@Override
	public PaginationResultVO<OrderLogisticsInfo> findListByPage(OrderLogisticsInfoQuery param) {
		return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> this.findListByParam(param));
	}

	@Override
	public Integer add(OrderLogisticsInfo bean) {
		return this.orderLogisticsInfoMapper.insert(bean);
	}

	@Override
	public Integer addBatch(List<OrderLogisticsInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderLogisticsInfoMapper.insertBatch(listBean);
	}

	@Override
	public Integer addOrUpdateBatch(List<OrderLogisticsInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderLogisticsInfoMapper.insertOrUpdateBatch(listBean);
	}

	@Override
	public Integer updateByParam(OrderLogisticsInfo bean, OrderLogisticsInfoQuery param) {
		StringTools.checkParam(param);
		return this.orderLogisticsInfoMapper.updateByParam(bean, param);
	}

	@Override
	public Integer deleteByParam(OrderLogisticsInfoQuery param) {
		StringTools.checkParam(param);
		return this.orderLogisticsInfoMapper.deleteByParam(param);
	}

	@Override
	public OrderLogisticsInfo getOrderLogisticsInfoByOrderId(String orderId) {
		return this.orderLogisticsInfoMapper.selectByOrderId(orderId);
	}

	@Override
	public Integer updateOrderLogisticsInfoByOrderId(OrderLogisticsInfo bean, String orderId) {
		return this.orderLogisticsInfoMapper.updateByOrderId(bean, orderId);
	}

	@Override
	public Integer deleteOrderLogisticsInfoByOrderId(String orderId) {
		return this.orderLogisticsInfoMapper.deleteByOrderId(orderId);
	}

	@Override
	public OrderLogisticsInfo getOrderLogisticsRecords(String userId, String orderId) {
		// 获得OrderLogisticsInfo
		OrderLogisticsInfo orderLogisticsInfo = this.getOrderLogisticsInfoByOrderId(orderId);
		if (orderLogisticsInfo == null) {
			throw new BusinessException("物流信息不存在");
		}
		if (!orderLogisticsInfo.getUserId().equals(userId) && userId != null){
			throw new BusinessException("物流信息不存在");
		}
		// 查询物流运输记录
		List<OrderLogisticsInfoRecord> recordList = new ArrayList<>();
		// 根据orderId查询，按recordId倒序排序
		OrderLogisticsInfoRecordQuery recordQuery = new OrderLogisticsInfoRecordQuery();
		recordQuery.setOrderId(orderId);
		recordQuery.setOrderBy(com.smartlect.entity.query.SafeSort.of("record_id desc"));
		recordList = orderLogisticsInfoRecordService.findListByParam(recordQuery);
		orderLogisticsInfo.setRecordList(recordList);
		return orderLogisticsInfo;
	}

	@Override
	@Transactional(rollbackFor = Exception.class)
	public void delivery(OrderLogisticsInfo orderLogisticsInfo) {
		OrderLogisticsInfoQuery query = new OrderLogisticsInfoQuery();
		orderLogisticsInfo.setLogisticsStatus(LogisticsStatusEnum.IN_TRANSIT.getStatus());
		query.setOrderId(orderLogisticsInfo.getOrderId());
		Integer count = this.updateByParam(orderLogisticsInfo, query);
		if (count != 1) {
			throw new BusinessException("该订单已经发货过了");
		}
		// 修改订单状态为已发货（状态机 CAS：PAID→SHIPPED，0 行即已被并发发货）
		count = orderStateMachine.transition(orderLogisticsInfo.getOrderId(), OrderStatusEnum.PAID,
				OrderStateEvent.SHIP);
		if (count != 1) {
			throw new BusinessException("该订单已经发货过了");
		}
		// 将发货信息插入order_logistics_info_record表
		OrderLogisticsInfoRecord record = new OrderLogisticsInfoRecord();
		record.setOrderId(orderLogisticsInfo.getOrderId());
		record.setRecordTime(new Date());
		record.setRecordAddress(orderLogisticsInfo.getSenderAddress());
		orderLogisticsInfoRecordService.add(record);
		PayOrderMessageDTO confirmDto = new PayOrderMessageDTO(orderLogisticsInfo.getOrderId());
		transactionalMqSender.sendAfterCommit(
				RocketMqTopics.TOPIC_DELAY,
				RocketMqTopics.TAG_CONFIRM_RECEIPT,
				confirmDto,
				MqIdempotencyKeys.payConfirm(orderLogisticsInfo.getOrderId()),
				MessageReliabilityLevelEnum.STANDARD,
				System.currentTimeMillis() + RocketMqTopics.CONFIRM_RECEIPT.toMillis());
	}
}
