package com.smartlect.controller.admin;

import com.smartlect.entity.query.StatisticsInfoQuery;
import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.StatisticsInfoService;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("statisticsInfoController")
@RequestMapping("/admin/statisticsInfo")
@SaCheckPermission(value = {"analytics:read"}, orRole = "SUPER_ADMIN", type = "admin")
public class StatisticsInfoController extends com.smartlect.controller.admin.ABaseController {

	@Resource
	private StatisticsInfoService statisticsInfoService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(StatisticsInfoQuery query) {
		query.setOrderBy(com.smartlect.entity.query.SafeSort.of("statistics_date desc, data_type asc"));
		return getSuccessResponseVO(statisticsInfoService.findListByPage(query));
	}
}
