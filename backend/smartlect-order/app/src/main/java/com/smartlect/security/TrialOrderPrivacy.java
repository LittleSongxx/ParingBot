package com.smartlect.security;

import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.vo.PaginationResultVO;

import java.util.Collection;

public final class TrialOrderPrivacy {

    private static final String MASKED_BUYER = "作品集买家";
    private static final String MASKED = "***";

    private TrialOrderPrivacy() {
    }

    public static boolean active() {
        return TrialIdentities.isTrialAdmin(AdminSecurityContext.current());
    }

    public static <T> T redact(T payload) {
        if (!active() || payload == null) {
            return payload;
        }
        if (payload instanceof PaginationResultVO<?> page) {
            redactAll(page.getList());
            return payload;
        }
        if (payload instanceof Collection<?> items) {
            redactAll(items);
            return payload;
        }
        redactOne(payload);
        return payload;
    }

    private static void redactAll(Collection<?> items) {
        if (items == null) {
            return;
        }
        for (Object item : items) {
            redactOne(item);
        }
    }

    private static void redactOne(Object item) {
        if (item instanceof OrderLogisticsInfo logistics) {
            // 物流进度对展厅可见（订单页要用），但收/发货人姓名、电话、地址一律打码：
            // 这是"不查看用户隐私"承诺里最容易被漏掉的一面（2026-10-16 审计）。
            logistics.setReceiverName(MASKED);
            logistics.setReceiverPhone(MASKED);
            logistics.setReceiverAddress(MASKED);
            logistics.setSenderName(MASKED);
            logistics.setSenderPhone(MASKED);
            logistics.setSenderAddress(MASKED);
            logistics.setUserId(null);
            return;
        }
        if (item instanceof OrderInfo order) {
            order.setUserId(null);
            order.setNickName(MASKED_BUYER);
            order.setAvatar(null);
            if (order.getOrderItemList() != null) {
                for (OrderItem line : order.getOrderItemList()) {
                    line.setRemark(null);
                }
            }
            return;
        }
    }
}
