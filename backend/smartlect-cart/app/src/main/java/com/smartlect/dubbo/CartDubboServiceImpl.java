package com.smartlect.dubbo;

import com.smartlect.api.dubbo.CartDubboService;
import com.smartlect.api.dto.CartDeleteBatchDTO;
import com.smartlect.controller.internal.CartInternalController;
import com.smartlect.entity.vo.ResponseVO;
import jakarta.annotation.Resource;
import org.apache.dubbo.config.annotation.DubboService;

/**
 * 购物车域 Dubbo provider：委托 CartInternalController（双通道共用逻辑）。
 */
@DubboService
public class CartDubboServiceImpl implements CartDubboService {

    @Resource
    private CartInternalController cartInternalController;

    @Override
    public ResponseVO<Void> deleteBatch(CartDeleteBatchDTO dto) {
        return cartInternalController.deleteBatch(dto);
    }
}
