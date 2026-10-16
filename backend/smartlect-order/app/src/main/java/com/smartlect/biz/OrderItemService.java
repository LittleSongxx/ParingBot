package com.smartlect.biz;

import java.util.List;

import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.vo.PaginationResultVO;

public interface OrderItemService {

	List<OrderItem> findListByParam(OrderItemQuery param);

	Integer findCountByParam(OrderItemQuery param);

	PaginationResultVO<OrderItem> findListByPage(OrderItemQuery param);

	Integer add(OrderItem bean);

	Integer addBatch(List<OrderItem> listBean);

	Integer addOrUpdateBatch(List<OrderItem> listBean);

	Integer updateByParam(OrderItem bean,OrderItemQuery param);

	Integer deleteByParam(OrderItemQuery param);

	OrderItem getOrderItemByOrderItemId(String orderItemId);

	Integer updateOrderItemByOrderItemId(OrderItem bean,String orderItemId);

	/** 连带购买商品 id（供导购/内部 API 用；聚合查询属于领域逻辑，收在服务层） */
	List<String> selectCoPurchaseProductIds(String productId, List<String> productIds,
			List<String> excluded, int limit);

	/** 热销商品聚合行（列名由 mapper 决定，返回原始行以便上层按需映射） */
	List<java.util.Map<String, Object>> selectPopularProducts(List<String> productIds,
			List<String> excluded, int limit);


	Integer deleteOrderItemByOrderItemId(String orderItemId);

}
