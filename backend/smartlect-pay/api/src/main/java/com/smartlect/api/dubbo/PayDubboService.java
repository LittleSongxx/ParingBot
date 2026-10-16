package com.smartlect.api.dubbo;

import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.api.dto.PayCloseDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.dto.PayQueryDTO;
import com.smartlect.api.dto.PayRefundDTO;
import com.smartlect.api.dto.PayTradeCreateDTO;
import com.smartlect.api.dto.PayTradeStatusDTO;
import com.smartlect.api.dto.PayUrlRequestDTO;


/**
 * pay 域内部 Dubbo 契约（取代原 FeignClient，方法签名一致；
 * HTTP /internal 端点保留给 assistant 与运维，双通道共用同一 Service 层）。
 */
public interface PayDubboService {

    ResponseVO<java.util.Map<String, Object>> tradeStatus(PayTradeStatusDTO dto, String userId);

    ResponseVO<Void> assertSettled(PayTradeStatusDTO dto);

    ResponseVO<Void> createPending(PayTradeCreateDTO dto);

    ResponseVO<Void> markSuccess(PayTradeStatusDTO dto);

    ResponseVO<Void> markClosed(PayTradeStatusDTO dto);

    ResponseVO<Void> markRefunded(PayTradeStatusDTO dto);

    ResponseVO<PayInfoDTO> getPayUrl(PayUrlRequestDTO dto, String userId);

    ResponseVO<Void> refund(PayRefundDTO dto);

    ResponseVO<Void> closeOrder(PayCloseDTO dto);

    ResponseVO<PayOrderNotifyDTO> queryOrder(PayQueryDTO dto);

}
