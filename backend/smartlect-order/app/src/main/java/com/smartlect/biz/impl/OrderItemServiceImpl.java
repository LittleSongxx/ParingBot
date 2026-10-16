package com.smartlect.biz.impl;

import java.util.List;

import jakarta.annotation.Resource;

import org.springframework.stereotype.Service;

import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.biz.OrderItemService;
import com.smartlect.utils.StringTools;
import com.smartlect.utils.PageUtils;

@Service("orderItemService")
public class OrderItemServiceImpl implements OrderItemService {

	@Resource
	private OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;

	@Override
	public List<OrderItem> findListByParam(OrderItemQuery param) {
		return this.orderItemMapper.selectList(param);
	}

	@Override
	public Integer findCountByParam(OrderItemQuery param) {
		return this.orderItemMapper.selectCount(param);
	}

	@Override
	public PaginationResultVO<OrderItem> findListByPage(OrderItemQuery param) {
		return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> this.findListByParam(param));
	}

	@Override
	public Integer add(OrderItem bean) {
		return this.orderItemMapper.insert(bean);
	}

	@Override
	public Integer addBatch(List<OrderItem> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderItemMapper.insertBatch(listBean);
	}

	@Override
	public Integer addOrUpdateBatch(List<OrderItem> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderItemMapper.insertOrUpdateBatch(listBean);
	}

	@Override
	public Integer updateByParam(OrderItem bean, OrderItemQuery param) {
		StringTools.checkParam(param);
		return this.orderItemMapper.updateByParam(bean, param);
	}

	@Override
	public Integer deleteByParam(OrderItemQuery param) {
		StringTools.checkParam(param);
		return this.orderItemMapper.deleteByParam(param);
	}

	@Override
	public OrderItem getOrderItemByOrderItemId(String orderItemId) {
		return this.orderItemMapper.selectByOrderItemId(orderItemId);
	}

	@Override
	public Integer updateOrderItemByOrderItemId(OrderItem bean, String orderItemId) {
		return this.orderItemMapper.updateByOrderItemId(bean, orderItemId);
	}

	@Override
	public Integer deleteOrderItemByOrderItemId(String orderItemId) {
		return this.orderItemMapper.deleteByOrderItemId(orderItemId);
	}

	@Override
	public List<String> selectCoPurchaseProductIds(String productId, List<String> productIds,
			List<String> excluded, int limit) {
		return this.orderItemMapper.selectCoPurchaseProductIds(productId, productIds, excluded, limit);
	}

	@Override
	public List<java.util.Map<String, Object>> selectPopularProducts(List<String> productIds,
			List<String> excluded, int limit) {
		return this.orderItemMapper.selectPopularProducts(productIds, excluded, limit);
	}
}
