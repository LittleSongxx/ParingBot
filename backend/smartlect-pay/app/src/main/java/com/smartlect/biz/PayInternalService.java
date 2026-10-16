package com.smartlect.biz;

import com.smartlect.api.dto.PayCloseDTO;
import com.smartlect.api.dto.PayQueryDTO;
import com.smartlect.api.dto.PayRefundDTO;
import com.smartlect.api.dto.PayTradeCreateDTO;
import com.smartlect.api.dto.PayTradeStatusDTO;
import com.smartlect.api.dto.PayUrlRequestDTO;
import com.smartlect.component.SpringContext;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.exception.BusinessException;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class PayInternalService {

    @Resource
    private PayTradeRecordService payTradeRecordService;

    @Value("${smartlect.payment.mode:mock}")
    private String paymentMode;

    public java.util.Map<String, Object> tradeStatus(String userId, String payOrderId) {
        com.smartlect.entity.po.PayTradeRecord record = payTradeRecordService.findByPayOrderId(payOrderId);
        if (record == null) return java.util.Map.of("paymentStatus", "NOT_FOUND");
        com.smartlect.security.DelegatedUserIdentity.requireOwner(userId, record.getUserId());
        String status = record.getTradeStatus() == null ? "UNKNOWN" : switch (record.getTradeStatus()) {
            case 0 -> "PENDING";
            case 1 -> "PAID";
            case 2 -> "CLOSED";
            case 3 -> "REFUNDED";
            default -> "UNKNOWN";
        };
        return java.util.Map.of("payOrderId", record.getPayOrderId(), "paymentStatus", status,
                "amountCents", record.getPayAmount().movePointRight(2).longValueExact());
    }

    public void assertSettled(String payOrderId) {
        if (StringTools.isEmpty(payOrderId)) {
            throw new BusinessException("支付订单号无效");
        }
        com.smartlect.entity.po.PayTradeRecord record = payTradeRecordService.findByPayOrderId(payOrderId);
        if (record == null) {
            throw new BusinessException("支付意图不存在");
        }
        Integer status = record.getTradeStatus();
        if (status == null || (status != 1 && status != 3)) {
            throw new BusinessException("支付意图尚未确认成功");
        }
    }

    public void createPending(PayTradeCreateDTO dto) {
        payTradeRecordService.createPending(
                dto.getUserId(), dto.getPayOrderId(), dto.getOrderId(), dto.getPayAmount(), dto.getPayChannel());
    }

    public void markSuccess(PayTradeStatusDTO dto) {
        payTradeRecordService.markSuccess(dto.getPayOrderId(), dto.getChannelOrderId());
    }

    public void markClosed(PayTradeStatusDTO dto) {
        payTradeRecordService.markClosed(dto.getPayOrderId());
    }

    public void markRefunded(PayTradeStatusDTO dto) {
        payTradeRecordService.markRefunded(dto.getPayOrderId());
    }

    public PayInfoDTO getPayUrl(PayUrlRequestDTO dto) {
        // 归属校验（2026-10-16 审计 M-2）：取支付表单也是"用户数据操作"——同文件 tradeStatus
        // 与渠道完成路径都有 requireOwner，这里此前没有，任意 payOrderId 可换回金额与 orderId。
        com.smartlect.entity.po.PayTradeRecord record = payTradeRecordService.findByPayOrderId(dto.getPayOrderId());
        if (record != null) {
            // 用委托身份头校验（DTO 里没有 userId 字段，且 require() 会在缺头时 fail-closed）：
            // 调用方必须是该支付单所属用户，否则不返回支付表单。
            String actor = com.smartlect.security.DelegatedUserIdentity.require();
            com.smartlect.security.DelegatedUserIdentity.requireOwner(actor, record.getUserId());
        }
        PayChannel channel = resolveChannel(dto.getPayChannel());
        PayChannelEnum channelEnum = PayChannelEnum.resolve(dto.getPayChannel());
        return channel.getPayUrl(channelEnum, dto.getPayOrderId(), dto.getSubject(), dto.getAmount());
    }

    public void refund(PayRefundDTO dto) {
        resolveChannel(dto.getPayChannel()).refund(
                dto.getSourcePayOrderId(), dto.getRefundOrderId(), dto.getRefundAmount());
    }

    public void closeOrder(PayCloseDTO dto) {
        resolveChannel(dto.getPayChannel()).closeOrder(dto.getPayOrderId());
    }

    public PayOrderNotifyDTO queryOrder(PayQueryDTO dto) {
        return resolveChannel(dto.getPayChannel()).queryOrder(dto.getPayOrderId());
    }

    private PayChannel resolveChannel(String payChannel) {
        if (StringTools.isEmpty(payChannel)) {
            throw new BusinessException("支付渠道为空");
        }
        PayChannelEnum channelEnum = PayChannelEnum.resolve(payChannel);
        if (channelEnum == null) {
            throw new BusinessException("不支持的支付渠道");
        }
        if (!"live".equals(paymentMode) && channelEnum != PayChannelEnum.MOCK) {
            throw new BusinessException("模拟支付模式禁止调用真实支付渠道");
        }
        return (PayChannel) SpringContext.getBean(channelEnum.getBeanName());
    }
}
