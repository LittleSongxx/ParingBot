package com.smartlect.api.support;

import com.smartlect.api.dubbo.PayDubboService;
import com.smartlect.api.dto.PayCloseDTO;
import com.smartlect.api.dto.PayQueryDTO;
import com.smartlect.api.dto.PayRefundDTO;
import com.smartlect.api.dto.PayTradeCreateDTO;
import com.smartlect.api.dto.PayTradeStatusDTO;
import com.smartlect.api.dto.PayUrlRequestDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import jakarta.annotation.Resource;
import org.apache.dubbo.config.annotation.DubboReference;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;

@Component
public class PayFeignSupport {

    @DubboReference
    private PayDubboService payFeignClient;
    @Resource
    private FeignResponseSupport feignResponseSupport;

    public java.util.Map<String, Object> tradeStatus(String userId, String payOrderId) {
        return feignResponseSupport.call(() -> payFeignClient.tradeStatus(new PayTradeStatusDTO(payOrderId), userId),
                "查询支付意图失败");
    }

    public void assertSettled(String payOrderId) {
        feignResponseSupport.run(
                () -> payFeignClient.assertSettled(new PayTradeStatusDTO(payOrderId)),
                "核对支付意图失败");
    }

    public void createPending(String userId, String payOrderId, String orderId, BigDecimal payAmount, String payChannel) {
        feignResponseSupport.run(
                () -> payFeignClient.createPending(new PayTradeCreateDTO(userId, payOrderId, orderId, payAmount, payChannel)),
                "创建支付流水失败");
    }

    public void markSuccess(String payOrderId, String channelOrderId) {
        feignResponseSupport.run(
                () -> payFeignClient.markSuccess(new PayTradeStatusDTO(payOrderId, channelOrderId)),
                "更新支付成功失败");
    }

    public void markClosed(String payOrderId) {
        feignResponseSupport.run(
                () -> payFeignClient.markClosed(new PayTradeStatusDTO(payOrderId)),
                "关闭支付流水失败");
    }

    public void markRefunded(String payOrderId) {
        feignResponseSupport.run(
                () -> payFeignClient.markRefunded(new PayTradeStatusDTO(payOrderId)),
                "更新退款状态失败");
    }

    public PayInfoDTO getPayUrl(String payChannel, String payOrderId, String subject, BigDecimal amount) {
        return feignResponseSupport.call(
                () -> payFeignClient.getPayUrl(new PayUrlRequestDTO(payChannel, payOrderId, subject, amount)),
                "获取支付链接失败");
    }

    public void refund(String sourcePayOrderId, String refundOrderId, BigDecimal refundAmount, String payChannel) {
        feignResponseSupport.run(
                () -> payFeignClient.refund(new PayRefundDTO(sourcePayOrderId, refundOrderId, refundAmount, payChannel)),
                "支付退款失败");
    }

    public void closeOrder(String payOrderId, String payChannel) {
        feignResponseSupport.run(
                () -> payFeignClient.closeOrder(new PayCloseDTO(payOrderId, payChannel)),
                "关闭支付渠道订单失败");
    }

    public PayOrderNotifyDTO queryOrder(String payOrderId, String payChannel) {
        return feignResponseSupport.call(
                () -> payFeignClient.queryOrder(new PayQueryDTO(payOrderId, payChannel)),
                "查询支付订单失败");
    }
}
