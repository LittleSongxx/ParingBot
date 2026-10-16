package com.smartlect.biz.impl;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import com.smartlect.api.support.OrderRpcSupport;
import com.smartlect.api.support.UserRpcSupport;
import com.smartlect.api.vo.OrderDailyStatsVO;
import com.smartlect.api.vo.OrderRangeStatsVO;
import com.smartlect.biz.StatisticsInfoService;
import com.smartlect.entity.enums.DateTimePatternEnum;
import com.smartlect.entity.enums.StatisticsDataTypeEnum;
import com.smartlect.entity.po.StatisticsInfo;
import com.smartlect.entity.query.StatisticsInfoQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.StatisticsDataVO;
import com.smartlect.entity.vo.TodayDataVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.StatisticsInfoMapper;
import com.smartlect.utils.DateUtil;
import com.smartlect.utils.PageUtils;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service("statisticsInfoService")
public class StatisticsInfoServiceImpl implements StatisticsInfoService {

	private static final Logger log = LoggerFactory.getLogger(StatisticsInfoServiceImpl.class);

	@Resource
	private StatisticsInfoMapper<StatisticsInfo, StatisticsInfoQuery> statisticsInfoMapper;
	@Resource
	private OrderRpcSupport orderRpcSupport;
	@Resource
	private UserRpcSupport userRpcSupport;

	@Override
	public PaginationResultVO<StatisticsInfo> findListByPage(StatisticsInfoQuery param) {
		return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> statisticsInfoMapper.selectList(param));
	}

	@Override
	public List<TodayDataVO> getTodayData() {
		String nowEnd = DateUtil.getTimeOnParttern(0, DateTimePatternEnum.YYYY_MM_DD_HH_MM_SS.getPattern());
		String todayDate = DateUtil.getTimeOnParttern(0, DateTimePatternEnum.YYYY_MM_DD.getPattern());
		String yesterdayDate = DateUtil.getTimeOnParttern(1, DateTimePatternEnum.YYYY_MM_DD.getPattern());
		String todayStart = todayDate + " 00:00:00";
		String yesterdayStart = yesterdayDate + " 00:00:00";
		String yesterdayEnd = yesterdayDate + " 23:59:59";

		OrderRangeStatsVO yesterdaySale = orderRpcSupport.aggregateRange(yesterdayStart, yesterdayEnd);
		OrderRangeStatsVO todaySale = orderRpcSupport.aggregateRange(todayStart, nowEnd);
		if (yesterdaySale == null) {
			yesterdaySale = new OrderRangeStatsVO();
		}
		if (todaySale == null) {
			todaySale = new OrderRangeStatsVO();
		}

		BigDecimal yesterdayUserCount = new BigDecimal(userRpcSupport.countByJoinDate(yesterdayDate, yesterdayDate));
		BigDecimal todayUserCount = new BigDecimal(userRpcSupport.countByJoinDate(todayDate, todayDate));

		List<TodayDataVO> todayDataVOList = new ArrayList<>();
		todayDataVOList.add(new TodayDataVO("orderAmount", todaySale.getSaleAmount(), yesterdaySale.getSaleAmount()));
		todayDataVOList.add(new TodayDataVO("orderCount", todaySale.getSaleOrderCount(), yesterdaySale.getSaleOrderCount()));
		todayDataVOList.add(new TodayDataVO("userCount", todayUserCount, yesterdayUserCount));
		todayDataVOList.add(new TodayDataVO("refundAmount", todaySale.getRefundAmount(), yesterdaySale.getRefundAmount()));
		return todayDataVOList;
	}

	@Override
	public List<StatisticsDataVO> loadWeeklyStatisticsData() {
		String startTime = DateUtil.getTimeOnParttern(8, DateTimePatternEnum.YYYY_MM_DD.getPattern());
		String endTime = DateUtil.getTimeOnParttern(0, DateTimePatternEnum.YYYY_MM_DD.getPattern());
		StatisticsInfoQuery statisticsInfoQuery = new StatisticsInfoQuery();
		statisticsInfoQuery.setQueryStartTime(startTime);
		statisticsInfoQuery.setQueryEndTime(endTime);
		List<StatisticsInfo> statisticsInfoList = statisticsInfoMapper.selectList(statisticsInfoQuery);

		List<String> last7Days = new ArrayList<>();
		java.time.format.DateTimeFormatter fmt = java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd");
		for (int i = 6; i >= 0; i--) {
			last7Days.add(java.time.LocalDate.now().minusDays(i).format(fmt));
		}

		java.util.Map<String, java.util.Map<Integer, BigDecimal>> map = new java.util.HashMap<>();
		for (StatisticsInfo si : statisticsInfoList) {
			java.util.Map<Integer, BigDecimal> typeMap = map.computeIfAbsent(si.getStatisticsDate(), k -> new java.util.HashMap<>());
			typeMap.put(si.getDataType(), si.getDataValue());
		}

		List<BigDecimal> orderAmount = new ArrayList<>();
		List<BigDecimal> orderCount = new ArrayList<>();
		List<BigDecimal> refundAmount = new ArrayList<>();
		List<BigDecimal> refundCount = new ArrayList<>();
		List<String> dateList = new ArrayList<>();
		String today = java.time.LocalDate.now().format(fmt);
		String nowEnd = DateUtil.getTimeOnParttern(0, DateTimePatternEnum.YYYY_MM_DD_HH_MM_SS.getPattern());
		OrderRangeStatsVO liveToday = orderRpcSupport.aggregateRange(today + " 00:00:00", nowEnd);
		if (liveToday == null) {
			liveToday = new OrderRangeStatsVO();
		}
		for (String day : last7Days) {
			dateList.add(day);
			java.util.Map<Integer, BigDecimal> typeMap = map.get(day);
			BigDecimal amount = typeMap != null ? typeMap.getOrDefault(StatisticsDataTypeEnum.SALE_AMOUNT.getType(), BigDecimal.ZERO) : BigDecimal.ZERO;
			BigDecimal count = typeMap != null ? typeMap.getOrDefault(StatisticsDataTypeEnum.SALE_COUNT.getType(), BigDecimal.ZERO) : BigDecimal.ZERO;
			BigDecimal refund = typeMap != null ? typeMap.getOrDefault(StatisticsDataTypeEnum.REFUND_AMOUNT.getType(), BigDecimal.ZERO) : BigDecimal.ZERO;
			BigDecimal refunds = typeMap != null ? typeMap.getOrDefault(StatisticsDataTypeEnum.REFUND_COUNT.getType(), BigDecimal.ZERO) : BigDecimal.ZERO;
			if (today.equals(day)) {
				amount = nz(liveToday.getSaleAmount());
				count = nz(liveToday.getSaleOrderCount());
				refund = nz(liveToday.getRefundAmount());
			}
			orderAmount.add(amount);
			orderCount.add(count);
			refundAmount.add(refund);
			refundCount.add(refunds);
		}

		StatisticsDataVO orderAmountVO = new StatisticsDataVO();
		StatisticsDataVO orderCountVO = new StatisticsDataVO();
		StatisticsDataVO refundAmountVO = new StatisticsDataVO();
		StatisticsDataVO refundCountVO = new StatisticsDataVO();
		orderAmountVO.setDataType(StatisticsDataTypeEnum.SALE_AMOUNT.getType());
		orderAmountVO.setDataList(orderAmount);
		orderAmountVO.setDateList(dateList);
		orderCountVO.setDataType(StatisticsDataTypeEnum.SALE_COUNT.getType());
		orderCountVO.setDataList(orderCount);
		orderCountVO.setDateList(dateList);
		refundAmountVO.setDataType(StatisticsDataTypeEnum.REFUND_AMOUNT.getType());
		refundAmountVO.setDataList(refundAmount);
		refundAmountVO.setDateList(dateList);
		refundCountVO.setDataType(StatisticsDataTypeEnum.REFUND_COUNT.getType());
		refundCountVO.setDataList(refundCount);
		refundCountVO.setDateList(dateList);
		List<StatisticsDataVO> statisticsDataVOList = new ArrayList<>();
		statisticsDataVOList.add(orderAmountVO);
		statisticsDataVOList.add(orderCountVO);
		statisticsDataVOList.add(refundAmountVO);
		statisticsDataVOList.add(refundCountVO);
		return statisticsDataVOList;
	}

	@Override
	// 不标 @Transactional：方法开头要调 orderRpcSupport.aggregateDaily 拉跨服务聚合，
	// 放在事务里会让数据库连接在整个聚合查询期间被占住（日结只跑一次，但聚合可能数秒）。
	// 后续 saveStatistics 是主键 upsert、逐日幂等，去掉整体事务后各日各自提交，
	// 即便中途失败，下次跑该任务会重算覆盖，不会留下半成品。
	public void statistics(String startTime, String endTime) {
		if (startTime == null) {
			startTime = DateUtil.getTimeOnParttern(14, DateTimePatternEnum.YYYY_MM_DD.getPattern()) + " 01:00:00";
		}
		if (endTime == null) {
			endTime = DateUtil.getTimeOnParttern(0, DateTimePatternEnum.YYYY_MM_DD.getPattern()) + " 01:00:00";
		}
		List<OrderDailyStatsVO> dailyList = orderRpcSupport.aggregateDaily(startTime, endTime);
		if (dailyList == null || dailyList.isEmpty()) {
			log.info("statistics() no order buckets for {} ~ {}", startTime, endTime);
			return;
		}
		for (OrderDailyStatsVO day : dailyList) {
			if (day == null || StringTools.isEmpty(day.getStatisticsDate())) {
				continue;
			}
			saveStatistics(day.getStatisticsDate(),
					nz(day.getSaleAmount()), nz(day.getSaleCount()),
					nz(day.getRefundAmount()), nz(day.getRefundCount()));
		}
	}

	private BigDecimal nz(BigDecimal v) {
		return v == null ? BigDecimal.ZERO : v;
	}

	private void saveStatistics(String pDate, BigDecimal saleAmount, BigDecimal saleCount,
			BigDecimal refundAmount, BigDecimal refundCount) {
		StatisticsInfo statisticsInfo = new StatisticsInfo();
		statisticsInfo.setStatisticsDate(pDate);
		statisticsInfo.setDataType(StatisticsDataTypeEnum.SALE_AMOUNT.getType());
		statisticsInfo.setDataValue(saleAmount);
		Integer c1 = statisticsInfoMapper.insertOrUpdate(statisticsInfo);
		statisticsInfo.setDataType(StatisticsDataTypeEnum.SALE_COUNT.getType());
		statisticsInfo.setDataValue(saleCount);
		Integer c2 = statisticsInfoMapper.insertOrUpdate(statisticsInfo);
		statisticsInfo.setDataType(StatisticsDataTypeEnum.REFUND_AMOUNT.getType());
		statisticsInfo.setDataValue(refundAmount);
		Integer c3 = statisticsInfoMapper.insertOrUpdate(statisticsInfo);
		statisticsInfo.setDataType(StatisticsDataTypeEnum.REFUND_COUNT.getType());
		statisticsInfo.setDataValue(refundCount);
		Integer c4 = statisticsInfoMapper.insertOrUpdate(statisticsInfo);
		// MySQL 的 INSERT ... ON DUPLICATE KEY UPDATE 在"行已存在且值未变"时返回 0 行——
		// 这不是失败，而是重复执行（多副本、启动补齐、管理员手工重跑）的正常结果。
		// 按 0 行抛错会让第二个执行者整笔回滚并误报"统计异常"，只有 null 才是写失败。
		if (c1 == null || c2 == null || c3 == null || c4 == null) {
			throw new BusinessException("统计异常");
		}
	}
}
