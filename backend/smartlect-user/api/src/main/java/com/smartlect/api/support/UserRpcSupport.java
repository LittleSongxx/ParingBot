package com.smartlect.api.support;

import com.smartlect.api.dubbo.UserDubboService;
import com.smartlect.api.dto.UserAddressQueryDTO;
import com.smartlect.api.dto.UserIdsDTO;
import com.smartlect.api.dto.UserJoinCountDTO;
import com.smartlect.api.vo.UserAddressVO;
import com.smartlect.api.vo.UserBriefVO;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.apache.dubbo.config.annotation.DubboReference;
import org.springframework.stereotype.Component;

import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

@Slf4j
@Component
public class UserRpcSupport {

    @DubboReference
    private UserDubboService userDubboService;
    @Resource
    private RpcResponseSupport rpcResponseSupport;

    public UserAddressVO getAddress(String addressId, String userId) {
        return rpcResponseSupport.call(
                () -> userDubboService.getAddress(new UserAddressQueryDTO(addressId, userId), userId),
                "查询收货地址失败");
    }

    public List<String> listAllUserIds() {
        try {
            List<String> ids = rpcResponseSupport.call(
                    () -> userDubboService.listAllUserIds(),
                    "查询用户列表失败");
            return ids == null ? Collections.emptyList() : ids;
        } catch (Exception e) {
            log.warn("查询全部用户ID降级为空: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    public Map<String, UserBriefVO> mapBriefByUserIds(List<String> userIds) {
        if (userIds == null || userIds.isEmpty()) {
            return Collections.emptyMap();
        }
        try {
            List<UserBriefVO> list = rpcResponseSupport.call(
                    () -> userDubboService.listBriefByUserIds(new UserIdsDTO(userIds)),
                    "批量查询用户信息失败");
            if (list == null || list.isEmpty()) {
                return Collections.emptyMap();
            }
            return list.stream()
                    .filter(u -> u != null && u.getUserId() != null)
                    .collect(Collectors.toMap(UserBriefVO::getUserId, Function.identity(), (a, b) -> a));
        } catch (Exception e) {
            log.warn("批量查询用户信息降级为空: {}", e.getMessage());
            return new HashMap<>();
        }
    }

    public Integer countByJoinDate(String joinDateStart, String joinDateEnd) {
        Integer count = rpcResponseSupport.call(
                () -> userDubboService.countByJoinDate(new UserJoinCountDTO(joinDateStart, joinDateEnd)),
                "统计新用户失败");
        return count == null ? 0 : count;
    }
}
