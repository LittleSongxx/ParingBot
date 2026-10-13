package com.smartlect.dubbo;

import com.smartlect.api.dto.UserAddressQueryDTO;
import com.smartlect.api.dto.UserIdsDTO;
import com.smartlect.api.dto.UserJoinCountDTO;
import com.smartlect.api.dubbo.UserDubboService;
import com.smartlect.api.vo.UserAddressVO;
import com.smartlect.api.vo.UserBriefVO;
import com.smartlect.controller.internal.UserInternalController;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.*;
import jakarta.annotation.Resource;
import org.apache.dubbo.config.annotation.DubboService;

import java.util.List;

/**
 * 用户域 Dubbo provider：与 UserInternalController 共用同一 Service 层。
 * 委托用户一致性校验沿用 HTTP 通道 DelegatedUserIdentity 的语义（显式参数
 * 替代请求头，Dubbo 调用无 HTTP 上下文）。
 */
@DubboService
public class UserDubboServiceImpl implements UserDubboService {

    @Resource
    private UserInternalController userInternalController;

    @Override
    public ResponseVO<UserAddressVO> getAddress(UserAddressQueryDTO dto, String userId) {
        com.smartlect.security.DelegatedUserIdentity.setDubboDelegated(userId);
        try {
            return userInternalController.getAddress(dto);
        } finally {
            com.smartlect.security.DelegatedUserIdentity.clearDubboDelegated();
        }
    }

    @Override
    public ResponseVO<List<String>> listAllUserIds() {
        return userInternalController.listAllUserIds();
    }

    @Override
    public ResponseVO<List<UserBriefVO>> listBriefByUserIds(UserIdsDTO dto) {
        return userInternalController.listBriefByUserIds(dto);
    }

    @Override
    public ResponseVO<Integer> countByJoinDate(UserJoinCountDTO dto) {
        return userInternalController.countByJoinDate(dto);
    }

}
