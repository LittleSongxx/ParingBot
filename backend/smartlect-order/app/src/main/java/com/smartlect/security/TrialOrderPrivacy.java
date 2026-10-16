package com.smartlect.security;

import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.po.OrderLogisticsInfoRecord;
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
            // 轨迹记录逐条脱敏：getLogistics 的响应会内嵌 recordList，只打码主体字段
            // 会把 record_address（末站即收件人地址）整条漏出去（2026-10-17 审计 H1）
            if (logistics.getRecordList() != null) {
                for (OrderLogisticsInfoRecord record : logistics.getRecordList()) {
                    redactOne(record);
                }
            }
            return;
        }
        if (item instanceof OrderLogisticsInfoRecord record) {
            // record_address：中间站是城市，末站由 LogisticsStepListener 写入完整收件地址
            record.setRecordAddress(MASKED);
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
        if (item instanceof OrderItem line) {
            // 独立走 /admin/orderItem/** 的明细：买家备注属买家原文，展厅视角一律抹掉
            // （2026-10-17 审计 H1）
            line.setRemark(null);
        }
    }
}
