package com.smartlect.api.support;

import com.smartlect.api.dubbo.CartDubboService;
import com.smartlect.api.dto.CartDeleteBatchDTO;
import com.smartlect.api.dto.CartDeleteItemDTO;
import jakarta.annotation.Resource;
import org.apache.dubbo.config.annotation.DubboReference;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
public class CartFeignSupport {

    @DubboReference
    private CartDubboService cartFeignClient;
    @Resource
    private FeignResponseSupport feignResponseSupport;

    public void deleteBatch(List<CartDeleteItemDTO> items) {
        if (items == null || items.isEmpty()) {
            return;
        }
        feignResponseSupport.run(
                () -> cartFeignClient.deleteBatch(new CartDeleteBatchDTO(items)),
                "清理购物车失败");
    }
}
