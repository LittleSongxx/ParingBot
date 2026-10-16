package com.smartlect.api.dubbo;

import com.smartlect.api.dto.CartDeleteBatchDTO;
import com.smartlect.entity.vo.ResponseVO;

/**
 * 购物车域内部 Dubbo 契约（取代 CartDubboService）。
 */
public interface CartDubboService {

    ResponseVO<Void> deleteBatch(CartDeleteBatchDTO dto);
}
