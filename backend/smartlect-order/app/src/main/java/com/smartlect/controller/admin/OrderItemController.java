package com.smartlect.controller.admin;

import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.OrderItemService;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("orderItemController")
@RequestMapping("/admin/orderItem")
public class OrderItemController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private OrderItemService orderItemService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(OrderItemQuery query){
		return getSuccessResponseVO(com.smartlect.security.TrialOrderPrivacy.redact(
				orderItemService.findListByPage(query)));
	}

	@PostMapping("/getOrderItemByOrderItemId")
	public ResponseVO getOrderItemByOrderItemId(String orderItemId) {
		return getSuccessResponseVO(com.smartlect.security.TrialOrderPrivacy.redact(
				orderItemService.getOrderItemByOrderItemId(orderItemId)));
	}

}
