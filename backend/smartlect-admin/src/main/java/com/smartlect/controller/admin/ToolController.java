package com.smartlect.controller.admin;

import com.smartlect.api.support.OrderFeignSupport;
import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.StatisticsInfoService;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RequestMapping("/admin/tool")
@RestController
@Slf4j
@SaCheckPermission(value = {"ops:tool"}, orRole = "SUPER_ADMIN", type = "admin")
public class ToolController extends com.smartlect.controller.admin.ABaseController {

    @Resource
    private StatisticsInfoService statisticsInfoService;
    @Resource
    private OrderFeignSupport orderFeignSupport;

    @PostMapping("/statistics")
    public ResponseVO statistics() {
        statisticsInfoService.statistics(null, null);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/addAllOrderToDelayQueue")
    public ResponseVO addAllOrderToDelayQueue() {
        orderFeignSupport.addAllWaitPayToDelayQueue();
        return getSuccessResponseVO(null);
    }
}
