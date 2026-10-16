package com.smartlect.biz.impl;

import com.smartlect.entity.po.UserAddress;
import com.smartlect.exception.BusinessException;
import com.smartlect.entity.query.UserAddressQuery;
import com.smartlect.mappers.UserAddressMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/**
 * 地址归属回归网：更新路径此前没有 owner 检查，而更新语句会 SET user_id——
 * 拿到他人 addressId 即可把整行改到自己名下（2026-10-16 审计）。
 */
class UserAddressOwnershipTest {

    @SuppressWarnings("unchecked")
    private final UserAddressMapper<UserAddress, UserAddressQuery> mapper = mock(UserAddressMapper.class);
    private final UserAddressServiceImpl service = new UserAddressServiceImpl();

    private UserAddress address(String addressId, String userId) {
        UserAddress bean = new UserAddress();
        bean.setAddressId(addressId);
        bean.setUserId(userId);
        bean.setDefaultType(0);
        return bean;
    }

    @Test
    void updatingSomeoneElsesAddressIsRejectedAndNothingIsWritten() {
        ReflectionTestUtils.setField(service, "userAddressMapper", mapper);
        when(mapper.selectByAddressId("SL-VICTIM")).thenReturn(address("SL-VICTIM", "victim-1"));

        UserAddress attempt = address("SL-VICTIM", "attacker-1");

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.saveAddress(attempt));
        assertEquals("当前地址不属于该用户", error.getMessage());
        verify(mapper, never()).updateByAddressId(any(UserAddress.class), anyString());
    }

    @Test
    void updatingOwnAddressStillWorks() {
        ReflectionTestUtils.setField(service, "userAddressMapper", mapper);
        when(mapper.selectByAddressId("SL-OWN")).thenReturn(address("SL-OWN", "user-1"));
        when(mapper.updateByAddressId(any(UserAddress.class), eq("SL-OWN"))).thenReturn(1);

        service.saveAddress(address("SL-OWN", "user-1"));

        verify(mapper).updateByAddressId(any(UserAddress.class), eq("SL-OWN"));
    }

    @Test
    void updatingAnAddressThatNoLongerExistsIsRejected() {
        ReflectionTestUtils.setField(service, "userAddressMapper", mapper);
        when(mapper.selectByAddressId("SL-GONE")).thenReturn(null);

        assertThrows(BusinessException.class,
                () -> service.saveAddress(address("SL-GONE", "user-1")));
        verify(mapper, never()).updateByAddressId(any(UserAddress.class), anyString());
    }
}
