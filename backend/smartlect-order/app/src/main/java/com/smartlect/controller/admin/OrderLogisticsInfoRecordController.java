package com.smartlect.controller.admin;

import com.smartlect.entity.query.OrderLogisticsInfoRecordQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.OrderLogisticsInfoRecordService;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("orderLogisticsInfoRecordController")
@RequestMapping("/admin/orderLogisticsInfoRecord")
public class OrderLogisticsInfoRecordController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private OrderLogisticsInfoRecordService orderLogisticsInfoRecordService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(OrderLogisticsInfoRecordQuery query){
		return getSuccessResponseVO(com.smartlect.security.TrialOrderPrivacy.redact(
				orderLogisticsInfoRecordService.findListByPage(query)));
	}

	@PostMapping("/getOrderLogisticsInfoRecordByRecordId")
	public ResponseVO getOrderLogisticsInfoRecordByRecordId(Integer recordId) {
		return getSuccessResponseVO(com.smartlect.security.TrialOrderPrivacy.redact(
				orderLogisticsInfoRecordService.getOrderLogisticsInfoRecordByRecordId(recordId)));
	}

}
