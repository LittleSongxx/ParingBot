package com.smartlect.controller.admin;

import com.smartlect.entity.query.MqCompensationLogQuery;
import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.service.MqCompensationLogService;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/admin/mqCompensationLog")
@SaCheckPermission(value = {"ops:compensation-read"}, orRole = "SUPER_ADMIN", type = "admin")
public class MqCompensationLogController extends com.smartlect.controller.admin.ABaseController {

    @Resource
    private MqCompensationLogService mqCompensationLogService;

    @PostMapping("/loadDataList")
    public ResponseVO loadDataList(MqCompensationLogQuery query) {
        if (query.getOrderBy() == null) {
            query.setOrderBy(com.smartlect.entity.query.SafeSort.of("create_time desc"));
        }
        return getSuccessResponseVO(mqCompensationLogService.findListByPage(query));
    }

    @PostMapping("/getByLogId")
    public ResponseVO getByLogId(Integer logId) {
        return getSuccessResponseVO(mqCompensationLogService.getByLogId(logId));
    }

    // 运维更新处理状态：0待处理 1处理中 2已重放成功 3重放失败 4已忽略。
    // 写操作要求 ops:tool：类级是 ops:compensation-read（查询语义），此前"只读权限"下挂着写操作
    // （2026-10-16 审计），权限模型自相矛盾。
    @PostMapping("/updateStatus")
    @SaCheckPermission(value = {"ops:tool"}, orRole = "SUPER_ADMIN", type = "admin")
    public ResponseVO updateStatus(Integer logId, Integer status, String handleRemark) {
        mqCompensationLogService.updateHandleStatus(logId, status, handleRemark);
        return getSuccessResponseVO(null);
    }

    // 触发一次重放（释放发送幂等闸后重发）
    @PostMapping("/replay")
    @SaCheckPermission(value = {"ops:tool"}, orRole = "SUPER_ADMIN", type = "admin")
    public ResponseVO replay(Integer logId) {
        mqCompensationLogService.replay(logId);
        return getSuccessResponseVO(null);
    }
}
