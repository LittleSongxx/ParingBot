package com.smartlect.controller;

import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.po.ProductCart;
import com.smartlect.entity.query.ProductCartQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.api.vo.ProductCartVO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.biz.ProductCartService;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import cn.dev33.satoken.annotation.SaCheckLogin;

@RequestMapping("/productCart")
@RestController
public class ProductCartController extends ABaseController{

    @Resource
    private ProductCartService productCartService;

    // 加入购物车。事务边界留在 service（controller 只做鉴权与参数装配）——
    // controller 上开事务会让"事务范围 = HTTP 请求"成为隐式约定，后续加远程调用就会踩长事务。
    @PostMapping("/add2Cart")
    @SaCheckLogin
    public ResponseVO add2Cart(ProductCart productCart){
        TokenUserInfoDTO tokenUserInfo = getTokenUserInfo();
        if (tokenUserInfo == null || StringTools.isEmpty(tokenUserInfo.getUserId())) {
            throw new BusinessException("请先登录");
        }
        String userId = tokenUserInfo.getUserId();
        productCart.setUserId(userId);
        productCartService.add2Cart(productCart);
        return getSuccessResponseVO(null);
    }

    // 获取购物车列表
    @PostMapping("/loadProductCart")
    @SaCheckLogin
    public ResponseVO loadProductCart(@NotNull Integer pageNo){
        TokenUserInfoDTO tokenUserInfo = getTokenUserInfo();
        if (tokenUserInfo == null || StringTools.isEmpty(tokenUserInfo.getUserId())) {
            throw new BusinessException("请先登录");
        }
        String userId = tokenUserInfo.getUserId();
        ProductCartQuery param = new ProductCartQuery();
        param.setPageNo(pageNo);
        param.setPageSize(PageSize.SIZE15.getSize());
        // 按最后操作时间降序排序
        param.setOrderBy(com.smartlect.entity.query.SafeSort.of("last_update_time desc"));
        PaginationResultVO<ProductCartVO> result = productCartService.findListByPageAndUserId(param, userId);
        return getSuccessResponseVO(result);
    }

    // 移除购物车
    @PostMapping("/deleteCart")
    @SaCheckLogin
    public ResponseVO deleteCart(@NotEmpty String cartId){
        TokenUserInfoDTO tokenUserInfo = getTokenUserInfo();
        if (tokenUserInfo == null || StringTools.isEmpty(tokenUserInfo.getUserId())) {
            throw new BusinessException("请先登录");
        }
        String userId = tokenUserInfo.getUserId();
        ProductCartQuery param = new ProductCartQuery();
        param.setCartId(cartId);
        param.setUserId(userId);
        productCartService.deleteByParam(param);
        return getSuccessResponseVO(null);
    }
}
