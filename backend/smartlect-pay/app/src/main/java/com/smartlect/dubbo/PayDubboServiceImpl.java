package com.smartlect.dubbo;

import com.smartlect.api.dubbo.PayDubboService;
import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.*;
import jakarta.annotation.Resource;
import com.smartlect.controller.internal.PayInternalController;
import org.apache.dubbo.config.annotation.DubboService;

/**
 * pay 域 Dubbo provider：直接委托 internal controller（与 HTTP 通道共用
 * 校验、ResponseVO 包装与全部业务逻辑）。
 */
@DubboService
public class PayDubboServiceImpl implements PayDubboService {

    @Resource
    private PayInternalController payInternalController;

    @Override
    public ResponseVO<java.util.Map<String, Object>> tradeStatus(PayTradeStatusDTO dto, String userId) {
        com.smartlect.security.DelegatedUserIdentity.setDubboDelegated(userId);
        try {
            return payInternalController.tradeStatus(dto);
        } finally {
            com.smartlect.security.DelegatedUserIdentity.clearDubboDelegated();
        }
    }

    @Override
    public ResponseVO<Void> assertSettled(PayTradeStatusDTO dto) {
        return payInternalController.assertSettled(dto);
    }

    @Override
    public ResponseVO<Void> createPending(PayTradeCreateDTO dto) {
        return payInternalController.createPending(dto);
    }

    @Override
    public ResponseVO<Void> markSuccess(PayTradeStatusDTO dto) {
        return payInternalController.markSuccess(dto);
    }

    @Override
    public ResponseVO<Void> markClosed(PayTradeStatusDTO dto) {
        return payInternalController.markClosed(dto);
    }

    @Override
    public ResponseVO<Void> markRefunded(PayTradeStatusDTO dto) {
        return payInternalController.markRefunded(dto);
    }

    @Override
    public ResponseVO<PayInfoDTO> getPayUrl(PayUrlRequestDTO dto, String userId) {
        // 与 tradeStatus 同一模式：Dubbo 线程没有 HTTP 上下文，取表单前的归属校验
        // （PayInternalService.getPayUrl）依赖委托身份，必须由 provider 显式注入
        // ——2026-10-17 审计 H-1：此前不注入会让 every live getPayUrl 在记录存在时 401。
        com.smartlect.security.DelegatedUserIdentity.setDubboDelegated(userId);
        try {
            return payInternalController.getPayUrl(dto);
        } finally {
            com.smartlect.security.DelegatedUserIdentity.clearDubboDelegated();
        }
    }

    @Override
    public ResponseVO<Void> refund(PayRefundDTO dto) {
        return payInternalController.refund(dto);
    }

    @Override
    public ResponseVO<Void> closeOrder(PayCloseDTO dto) {
        return payInternalController.closeOrder(dto);
    }

    @Override
    public ResponseVO<PayOrderNotifyDTO> queryOrder(PayQueryDTO dto) {
        return payInternalController.queryOrder(dto);
    }

}
