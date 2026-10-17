package com.smartlect.controller.admin;

import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.api.dto.OrderStatusDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.biz.OrderLogisticsInfoService;
import com.smartlect.security.TrialOrderPrivacy;
import jakarta.annotation.Resource;
import jakarta.validation.constraints.NotEmpty;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import java.lang.reflect.Array;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@RequestMapping("/admin/order")
@RestController("adminOrderController")
public class OrderController extends com.smartlect.controller.admin.ABaseController{

    @Resource
    private OrderInfoService orderInfoService;
    @Resource
    private OrderLogisticsInfoService orderLogisticsInfoService;

    @PostMapping("/loadOrder")
    public ResponseVO loadOrder(Integer pageNo, Integer pageSize, String productNameFuzzy, Integer orderStatus){
        OrderInfoQuery orderInfoQuery = new OrderInfoQuery();
        // 查询所有订单
        orderInfoQuery.setQueryItems(true);
        orderInfoQuery.setQueryUser(true);
        orderInfoQuery.setOrderStatus(orderStatus);
        orderInfoQuery.setOrderBy(com.smartlect.entity.query.SafeSort.of("order_time desc"));
        orderInfoQuery.setPageNo(pageNo);
        orderInfoQuery.setPageSize(pageSize);
        PaginationResultVO<OrderInfo> resultVO = orderInfoService.findListByPage(orderInfoQuery);
        if (productNameFuzzy != null){
            // 对resultVO中的items进行过滤
            resultVO = orderInfoService.findByProductNameFuzzy(resultVO, productNameFuzzy);
        }
        return getSuccessResponseVO(TrialOrderPrivacy.redact(resultVO));
    }

    @PostMapping("/loadOrderStatus")
    public ResponseVO loadOrderStatus(){
        // 返回OrderStatusDTO
        List<OrderStatusDTO> orderStatusDTOList = new ArrayList<>();
        return getSuccessResponseVO(Arrays.stream(OrderStatusEnum.values())
                .map(OrderStatusDTO::getByStatus)
                .collect(Collectors.toList()));
    }

    // 获取收货地址
    @PostMapping("/getLogistics")
    public ResponseVO getLogistics(@NotEmpty String orderId){
        return getSuccessResponseVO(TrialOrderPrivacy.redact(
                orderLogisticsInfoService.getOrderLogisticsRecords(null, orderId)));
    }

    // 发货
    @PostMapping("/delivery")
    @SaCheckPermission(value = AdminPermissions.ORDER_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
    public ResponseVO delivery(OrderLogisticsInfo orderLogisticsInfo){
        orderLogisticsInfoService.delivery(orderLogisticsInfo);
        return getSuccessResponseVO(null);
    }
}
