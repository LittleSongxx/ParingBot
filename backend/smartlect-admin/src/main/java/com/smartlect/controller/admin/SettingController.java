package com.smartlect.controller.admin;

import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.component.RedisComponent;
import com.smartlect.entity.dto.LogisticsSendDTO;
import com.smartlect.entity.vo.ResponseVO;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RequestMapping("/admin/setting")
@RestController
public class SettingController extends com.smartlect.controller.admin.ABaseController{

    @Resource
    private RedisComponent redisComponent;

    // 保存系统发货地址
    @PostMapping("/saveLogistics")
    @SaCheckPermission(value = AdminPermissions.SETTINGS_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
    public ResponseVO saveLogistics(LogisticsSendDTO logisticsSendDTO){
        redisComponent.saveLogistics(logisticsSendDTO);
        return getSuccessResponseVO(null);
    }

    // 获取发货地址
    @PostMapping("/getLogistics")
    public ResponseVO getLogistics(){
        return getSuccessResponseVO(redisComponent.getLogisticsInfo());
    }


}
