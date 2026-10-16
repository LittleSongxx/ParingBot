package com.smartlect.security;

import com.smartlect.entity.dto.AdminPrincipalDTO;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderLogisticsInfo;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 订单域对展厅账号的脱敏：买家与收发件人 PII 打码，超管/普通管理员原样通过。
 *
 * <p>物流面是 2026-10-16 审计新增的覆盖（此前只脱敏 OrderInfo，收件人姓名/电话/地址
 * 经多条读接口直接漏出）。</p>
 */
class TrialOrderPrivacyTest {

    @AfterEach
    void clear() {
        AdminSecurityContext.clear();
    }

    private AdminPrincipalDTO principal(Set<String> roles, Set<String> permissions) {
        AdminPrincipalDTO dto = new AdminPrincipalDTO();
        dto.setRoles(roles);
        dto.setPermissions(permissions);
        return dto;
    }

    private OrderLogisticsInfo logistics() {
        OrderLogisticsInfo info = new OrderLogisticsInfo();
        info.setUserId("8800000002");
        info.setSenderName("王发货");
        info.setSenderPhone("13812345678");
        info.setSenderAddress("上海市浦东新区某路 1 号");
        info.setReceiverName("李收货");
        info.setReceiverPhone("13987654321");
        info.setReceiverAddress("北京市海淀区某路 2 号");
        return info;
    }

    @Test
    void trialAdminSeesMaskedBuyerAndLogisticsPii() {
        AdminSecurityContext.set(principal(Set.of("TRIAL_OPERATOR"), Set.of("admin:trial")));

        OrderLogisticsInfo masked = TrialOrderPrivacy.redact(logistics());

        assertEquals("***", masked.getReceiverName());
        assertEquals("***", masked.getReceiverPhone());
        assertEquals("***", masked.getReceiverAddress());
        assertEquals("***", masked.getSenderName());
        assertEquals("***", masked.getSenderPhone());
        assertNull(masked.getUserId());
    }

    @Test
    void superAdminSeesRealValues() {
        AdminSecurityContext.set(principal(Set.of("SUPER_ADMIN"), Set.of("admin:manage")));

        OrderLogisticsInfo info = logistics();
        OrderLogisticsInfo result = TrialOrderPrivacy.redact(info);

        assertSame(info, result);
        assertEquals("李收货", result.getReceiverName(), "非展厅身份不得被脱敏（否则发货流程没法用）");
        assertEquals("13987654321", result.getReceiverPhone());
        assertEquals("8800000002", result.getUserId());
    }

    @Test
    void trialAdminOrderRowsAreMaskedIncludingItemRemarks() {
        AdminSecurityContext.set(principal(Set.of("TRIAL_OPERATOR"), Set.of("admin:trial")));
        OrderInfo order = new OrderInfo();
        order.setUserId("8800000002");
        order.setNickName("小明");
        OrderItem line = new OrderItem();
        line.setRemark("送到前台");
        order.setOrderItemList(List.of(line));

        TrialOrderPrivacy.redact(order);

        assertNull(order.getUserId());
        assertEquals("作品集买家", order.getNickName());
        assertNull(line.getRemark());
    }

    @Test
    void missingPrincipalIsTreatedAsNonTrial() {
        AdminSecurityContext.clear();
        OrderLogisticsInfo info = logistics();

        TrialOrderPrivacy.redact(info);

        assertEquals("李收货", info.getReceiverName(), "没有 principal 时不得误伤（非管理端路径）");
    }
}
