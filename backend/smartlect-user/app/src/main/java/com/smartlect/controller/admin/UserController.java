package com.smartlect.controller.admin;

import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.component.RedisComponent;
import com.smartlect.component.UserTempBanService;
import com.smartlect.api.enums.UserStatusEnum;
import com.smartlect.entity.po.UserInfo;
import com.smartlect.entity.query.UserInfoQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.UserInfoService;
import jakarta.annotation.Resource;
import jakarta.validation.constraints.NotNull;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RequestMapping("/admin/user")
@RestController
public class UserController extends com.smartlect.controller.admin.ABaseController{

    @Resource
    private UserInfoService userInfoService;
    @Resource
    private RedisComponent redisComponent;
    @Resource
    private UserTempBanService userTempBanService;

    // 加载所有用户
    @PostMapping("/loadUser")
    public ResponseVO loadUser(Integer pageNo, Integer pageSize, Integer status, String nickNameFuzzy){
        UserInfoQuery userInfoQuery = new UserInfoQuery();
        userInfoQuery.setPageNo(pageNo);
        userInfoQuery.setPageSize(pageSize);
        userInfoQuery.setStatus(status);
        userInfoQuery.setNickNameFuzzy(nickNameFuzzy);
        userInfoQuery.setOrderBy(com.smartlect.entity.query.SafeSort.of("join_time desc"));
        PaginationResultVO<UserInfo> resultVO = userInfoService.findListByPage(userInfoQuery);
        return getSuccessResponseVO(resultVO);
    }

    // 改变用户状态
    @PostMapping("/changeStatus")
    @SaCheckPermission(value = AdminPermissions.USER_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
    public ResponseVO changeStatus(@NotNull String userId, @NotNull Integer status){
        // 根据userId查询用户
        UserInfo userInfo = userInfoService.getUserInfoByUserId(userId);
        userInfo.setStatus(status);
        userTempBanService.clearTempBanMark(userId);
        if (status.equals(UserStatusEnum.DISABLE.getStatus())) {
            redisComponent.cleanAllToken(userId);
        }
        userInfoService.updateUserInfoByUserId(userInfo, userId);
        return getSuccessResponseVO(null);
    }
}
