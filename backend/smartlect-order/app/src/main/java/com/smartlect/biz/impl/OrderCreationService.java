package com.smartlect.biz.impl;

import com.smartlect.api.dto.*;
import com.smartlect.api.enums.*;
import com.smartlect.api.support.*;
import com.smartlect.api.vo.*;
import com.smartlect.biz.OrderQuoteService;
import com.smartlect.biz.OrderRequestIdempotencyService;
import com.smartlect.component.RedisComponent;
import com.smartlect.component.RemoteCompensateRecorder;
import com.smartlect.metrics.SmartlectMetrics;
import com.smartlect.constants.Constants;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.dto.LogisticsSendDTO;
import com.smartlect.entity.po.*;
import com.smartlect.entity.query.*;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.OrderLogisticsInfoMapper;
import com.smartlect.support.MqIdempotencyKeys;
import com.smartlect.utils.OrderListPayAmountHelper;
import com.smartlect.utils.OrderPayAmountUtil;
import com.smartlect.utils.StringTools;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 下单领域服务（ADR-0019，拆自 OrderInfoServiceImpl）：
 * 报价（quote）、普通下单（postOrder）与 V2 报价确认（createConfirmed）三阶段编排——
 * 读准备 → 远程锁资源 → 短本地事务（订单 + Outbox 关单消息原子落库）→ 事务外幂等远程写 → 失败补偿。
 * 构造器注入；不持有任何 HTTP/查询职责。
 */
@Service
@Slf4j
public class OrderCreationService {

    private final OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    private final OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;
    private final OrderLogisticsInfoMapper<OrderLogisticsInfo, OrderLogisticsInfoQuery> orderLogisticsInfoMapper;
    private final OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper;
    private final TransactionTemplate transactionTemplate;
    private final UserRpcSupport userRpcSupport;
    private final ProductRpcSupport productRpcSupport;
    private final StockRpcSupport stockRpcSupport;
    private final CartRpcSupport cartRpcSupport;
    private final CouponRpcSupport couponRpcSupport;
    private final PayRpcSupport payRpcSupport;
    private final RedisComponent redisComponent;
    private final TransactionalMqSender transactionalMqSender;
    private final RemoteCompensateRecorder remoteCompensateRecorder;
    private final OrderRequestIdempotencyService orderRequestIdempotencyService;
    private final OrderQuoteService orderQuoteService;
    private final SmartlectMetrics metrics;

    public OrderCreationService(
            OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper,
            OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper,
            OrderLogisticsInfoMapper<OrderLogisticsInfo, OrderLogisticsInfoQuery> orderLogisticsInfoMapper,
            OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper,
            TransactionTemplate transactionTemplate,
            UserRpcSupport userRpcSupport,
            ProductRpcSupport productRpcSupport,
            StockRpcSupport stockRpcSupport,
            CartRpcSupport cartRpcSupport,
            CouponRpcSupport couponRpcSupport,
            PayRpcSupport payRpcSupport,
            RedisComponent redisComponent,
            TransactionalMqSender transactionalMqSender,
            RemoteCompensateRecorder remoteCompensateRecorder,
            OrderRequestIdempotencyService orderRequestIdempotencyService,
            OrderQuoteService orderQuoteService,
            SmartlectMetrics metrics) {
        this.orderInfoMapper = orderInfoMapper;
        this.orderItemMapper = orderItemMapper;
        this.orderLogisticsInfoMapper = orderLogisticsInfoMapper;
        this.orderCouponRelMapper = orderCouponRelMapper;
        this.transactionTemplate = transactionTemplate;
        this.userRpcSupport = userRpcSupport;
        this.productRpcSupport = productRpcSupport;
        this.stockRpcSupport = stockRpcSupport;
        this.cartRpcSupport = cartRpcSupport;
        this.couponRpcSupport = couponRpcSupport;
        this.payRpcSupport = payRpcSupport;
        this.redisComponent = redisComponent;
        this.transactionalMqSender = transactionalMqSender;
        this.remoteCompensateRecorder = remoteCompensateRecorder;
        this.orderRequestIdempotencyService = orderRequestIdempotencyService;
        this.orderQuoteService = orderQuoteService;
        this.metrics = metrics;
    }

    // 不标 @Transactional：createOrder 拆为三阶段（读准备 → 远程锁资源 → 短本地事务写入），
    // 远程调用不再占用数据库连接（压测实测 18.1s 连接占用 → 连接池抽干）。
    // 本地事务由 createOrder 内的 TransactionTemplate 管理，仅覆盖 DB 写入（毫秒级）。
    public PayInfoDTO postOrder(String userId, PostOrderDTO postOrderDTO, String idempotencyKey) {
        return orderRequestIdempotencyService.execute(
                userId,
                OrderRequestIdempotencyService.COMMAND_POST_ORDER,
                idempotencyKey,
                postOrderDTO,
                PayInfoDTO.class,
                () -> createOrder(userId, postOrderDTO, idempotencyKey));
    }

    // 方法体里唯一的事务性工作曾是把 couponRpcSupport.preview 的远程调用包住——
    // 远程调用期间数据库连接会被一直占住（同一反模式导致过支付/Outbox 连锁失败，
    // 见 confirmOrderReceipt 的注释）。方法内没有本地写需要原子保护，去掉了外层事务。
    public Map<String, Object> quoteOrder(String userId, PostOrderDTO request) {
        PreparedOrder prepared = prepareOrder(userId, request, null);
        if (!StringTools.isEmpty(request.getUserCouponId())) {
            BigDecimal gross = prepared.orders().stream().map(OrderInfo::getAmount)
                    .reduce(BigDecimal.ZERO, BigDecimal::add);
            CouponLockResultVO coupon = couponRpcSupport.preview(userId, request.getUserCouponId(), gross);
            if (coupon.getDiscountAmount() != null && coupon.getDiscountAmount().signum() > 0) {
                distributeCouponDiscount(prepared.orders(), coupon.getDiscountAmount());
                OrderListPayAmountHelper.ensureOrderListMinTotalPay(prepared.orders());
            }
        }
        return orderQuoteService.issue(userId, request, prepared.address(), prepared.items(), total(prepared.orders()));
    }

    // 同 postOrder：远程操作在事务外，本地写入用 TransactionTemplate 短事务。
    public PayInfoDTO createConfirmed(String userId, PostOrderDTO request, String quoteId,
            Long confirmedAmountCents, String idempotencyKey) {
        if (quoteId == null || confirmedAmountCents == null) OrderQuoteService.reconfirm();
        // Idempotency precedes quote expiry/consumption checks and all remote business reads.
        return orderRequestIdempotencyService.execute(userId,
                OrderRequestIdempotencyService.COMMAND_POST_ORDER_V2, idempotencyKey,
                Map.of("quoteId", quoteId, "confirmedAmountCents", confirmedAmountCents,
                        "order", OrderQuoteService.input(request)), PayInfoDTO.class, () -> {
            // claim-first：先在短事务内占用报价，再执行建单副作用（ADR-0018）。
            // 并发重复请求在占用处即被 409 挡下，不再先落单后才发现冲突留下孤儿订单。
            String claimedPayOrderId = StringTools.createPayOrderId();
            OrderQuoteService.Quote quote =
                    orderQuoteService.claim(userId, quoteId, claimedPayOrderId, request, confirmedAmountCents);
            try {
                return createOrder(userId, request, quote, confirmedAmountCents, claimedPayOrderId,
                        idempotencyKey);
            } catch (RuntimeException ex) {
                // 建单失败释放占用，报价可重新下单；释放失败则保持已占用（用户重新报价），不放大故障。
                if (!orderQuoteService.release(quoteId, userId, claimedPayOrderId)) {
                    log.warn("建单失败后释放报价占用失败, quoteId={}, payOrderId={}", quoteId, claimedPayOrderId);
                }
                throw ex;
            }
        });
    }

    PayInfoDTO createOrder(String userId, PostOrderDTO request, String idempotencyKey) {
        return createOrder(userId, request, null, null, null, idempotencyKey);
    }

    PayInfoDTO createOrder(String userId, PostOrderDTO postOrderDTO,
            OrderQuoteService.Quote quote, Long confirmedAmountCents, String presetPayOrderId,
            String orderIdempotencyKey) {
        // Phase 1: 只读准备（无本地事务，RPC 查地址/快照/库存预检不占连接）
        PreparedOrder prepared = prepareOrder(userId, postOrderDTO, presetPayOrderId);
        PayChannelEnum payChannelEnum = prepared.channel();
        OrderFromTypeEnum orderFromTypeEnum = prepared.from();
        List<ProductItem> newList = prepared.products();
        List<OrderInfo> orderInfoList = prepared.orders();
        List<OrderItem> orderItemList = prepared.items();
        List<CartDeleteItemDTO> productCartList = prepared.cart();
        List<OrderLogisticsInfo> orderLogisticsInfoList = prepared.logistics();
        String subject = prepared.subject();
        String unifiedPayOrderId = prepared.payOrderId();
        Date now = prepared.now();
        OrderCouponRel couponRel = null;
        if (newList.isEmpty()) {
            throw new BusinessException("请选择商品");
        }

        // Phase 2: 锁远程资源（远程服务各自事务，本地不持有连接）
        boolean couponLocked = false;
        boolean stockDeducted = false;
        List<ProductItem> deductList = copyItemsWithSignedBuyCount(newList, true);
        String userCouponId = postOrderDTO.getUserCouponId();
        if (!StringTools.isEmpty(userCouponId)) {
            BigDecimal orderAmountBeforeDiscount = orderInfoList.stream()
                    .map(OrderInfo::getAmount).reduce(BigDecimal.ZERO, BigDecimal::add);
            CouponLockResultVO lockResult = couponRpcSupport.validateAndLock(userId, userCouponId, orderAmountBeforeDiscount);
            if (Boolean.TRUE.equals(lockResult.getLocked()) && lockResult.getDiscountAmount() != null
                    && lockResult.getDiscountAmount().compareTo(BigDecimal.ZERO) > 0) {
                distributeCouponDiscount(orderInfoList, lockResult.getDiscountAmount());
                OrderListPayAmountHelper.ensureOrderListMinTotalPay(orderInfoList);
                OrderCouponRel rel = new OrderCouponRel();
                rel.setOrderId(orderInfoList.get(0).getOrderId());
                rel.setUserCouponId(userCouponId);
                rel.setCouponId(lockResult.getCouponId());
                rel.setDiscountAmount(lockResult.getDiscountAmount());
                rel.setCreateTime(now);
                couponRel = rel;
                couponLocked = true;
            }
        }
        try {
            if (quote != null) {
                orderQuoteService.validate(quote, userId, postOrderDTO, confirmedAmountCents,
                        prepared.address(), orderItemList, total(orderInfoList));
            }

            // Phase 3: 短本地事务（仅 DB 写入，毫秒级，不包含任何远程调用）。
            // 超时关单消息同事务写入 Outbox（ADR-0018）：订单落库与关单收敛消息同生共死——
            // 即使 Phase 4 扣库存/建支付意图失败，留下的待付款单也一定会在 15 分钟后被关闭，
            // 不再产生既无支付意图又无关单消息的永久孤儿订单。sendAfterCommit 在活跃事务内
            // 的语义：outbox 落库参与本事务，提交后异步投递不占本连接。
            final OrderCouponRel relToInsert = couponRel;
            transactionTemplate.executeWithoutResult(status -> {
                if (relToInsert != null) orderCouponRelMapper.insert(relToInsert);
                // 把下单命令的幂等键盖到每张子单上：对账任务据此反查"这个键有没有成交"
                // （审计 M8；历史行保持 NULL，迁移不回填）
                for (OrderInfo orderInfo : orderInfoList) {
                    orderInfo.setIdempotencyKey(orderIdempotencyKey);
                }
                orderInfoMapper.insertBatch(orderInfoList);
                orderItemMapper.insertBatch(orderItemList);
                orderLogisticsInfoMapper.insertBatch(orderLogisticsInfoList);
                for (OrderInfo orderInfo : orderInfoList) {
                    PayOrderMessageDTO dto = new PayOrderMessageDTO();
                    dto.setOrderId(orderInfo.getOrderId());
                    transactionalMqSender.sendAfterCommit(
                            com.smartlect.mq.RocketMqTopics.TOPIC_DELAY,
                            com.smartlect.mq.RocketMqTopics.TAG_PAY_TIMEOUT_CLOSE,
                            dto,
                            MqIdempotencyKeys.payTimeout(orderInfo.getOrderId()),
                            com.smartlect.entity.enums.MessageReliabilityLevelEnum.STANDARD,
                            System.currentTimeMillis() + com.smartlect.mq.RocketMqTopics.PAY_TIMEOUT.toMillis());
                }
            });
            // 下单成功口径：Phase 3 短事务提交即计入（Phase 4 失败走补偿，订单仍真实存在）
            metrics.orderCreated(orderInfoList.size());

            // Phase 4: 事务外远程写（幂等，失败不回滚订单——订单已随 Phase 3 携带超时关单消息：
            // 库存/券由 Phase 5 补偿回滚，遗留的待付款单由延时消息关闭，且库存服务对
            // "从未扣减过"的支付单不再回补，不会虚增库存）
            stockRpcSupport.changeStockBatch(deductList, "order-deduct:" + unifiedPayOrderId);
            stockDeducted = true;

            if (OrderFromTypeEnum.CART == orderFromTypeEnum) {
                cartRpcSupport.deleteBatch(productCartList);
            }
            BigDecimal totalAmount = orderInfoList.stream().map(OrderInfo::getAmount).reduce(BigDecimal.ZERO, BigDecimal::add);
            totalAmount = OrderPayAmountUtil.normalizeChannelPayAmount(totalAmount);
            log.info("提交订单,payOrderId={}, 订单数量={}, 总金额={}", unifiedPayOrderId, orderInfoList.size(), totalAmount);

            payRpcSupport.createPending(userId, unifiedPayOrderId, orderInfoList.get(0).getOrderId(),
                    totalAmount, postOrderDTO.getPayMethod());
            return requestInitialPayInfoBestEffort(
                    payChannelEnum.getPayScene(), unifiedPayOrderId, subject, totalAmount, userId);
        } catch (RuntimeException ex) {
            // Phase 5: 补偿（事务外，可独立重试）
            if (stockDeducted) {
                try {
                    stockRpcSupport.restoreOrderStock(
                            unifiedPayOrderId, copyItemsWithSignedBuyCount(newList, false));
                } catch (Exception compensateEx) {
                    log.error("下单失败后库存回补失败, payOrderId={}", unifiedPayOrderId, compensateEx);
                    // 记"按支付单回补"而不是裸批量变更：重放走 restoreOrderStock 的幂等键
                    // （order-close:{payOrderId,sku} + 前置 order-deduct 校验），
                    // 与直连回补同一条幂等链，重放不会双倍加库存（2026-10-16 审计 H3）
                    remoteCompensateRecorder.recordOrderStockRestore(
                            unifiedPayOrderId, copyItemsWithSignedBuyCount(newList, false), compensateEx);
                }
            }
            if (couponLocked) {
                try {
                    couponRpcSupport.changeUserCouponStatus(userCouponId, userId,
                            UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.NOUSE.getStatus(), null);
                } catch (Exception compensateEx) {
                    log.error("下单失败后优惠券解锁失败, payOrderId={}, userCouponId={}",
                            unifiedPayOrderId, userCouponId, compensateEx);
                    remoteCompensateRecorder.recordCouponUnlock(
                            unifiedPayOrderId, userCouponId, userId,
                            UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.NOUSE.getStatus(),
                            compensateEx);
                }
            }
            throw ex;
        }
    }

    private record PreparedOrder(PayChannelEnum channel, OrderFromTypeEnum from, UserAddressVO address,
            List<ProductItem> products, List<OrderInfo> orders, List<OrderItem> items,
            List<CartDeleteItemDTO> cart, List<OrderLogisticsInfo> logistics, String subject,
            String payOrderId, Date now) { }

    private PreparedOrder prepareOrder(String userId, PostOrderDTO postOrderDTO, String presetPayOrderId) {
        PayChannelEnum payChannelEnum = PayChannelEnum.getByPayScene(postOrderDTO.getPayMethod());
        if (payChannelEnum == null) {
            throw new BusinessException(com.smartlect.entity.enums.ResponseCodeEnum.CODE_600);
        }

        OrderFromTypeEnum orderFromTypeEnum = OrderFromTypeEnum.getByType(postOrderDTO.getOrderFrom());
        if (orderFromTypeEnum == null) {
            throw new BusinessException(com.smartlect.entity.enums.ResponseCodeEnum.CODE_600);
        }

        // PostOrderDTO中的数据有：订单列表(商品Id，商品属性Ids，购买数量，备注)，支付方式，地址ID，订单来源
        // 存入order_info表的数据有：订单Id，数量，用户Id，创建订单时间，订单状态，支付渠道，支付场景，支付订单Id，渠道订单Id，评价状态
        // 存入order_item表数据有：订单明细Id，订单Id，封面图，商品Id，商品名称，商品属性IdHash，property_info,item总价格，购买数量，订单明细状态，备注，refund_order_id
        // 同一个商品id的放在同一个订单中，分为不同的订单明细，同一个商品属性id的放在同一个订单明细中
        // 根据addressId获取地址信息（user 服务）
        UserAddressVO userAddress = userRpcSupport.getAddress(postOrderDTO.getAddressId(), userId);
        // 若地址不存在则抛出异常
        if (userAddress == null || StringTools.isEmpty(userAddress.getAddress())) {
            throw new BusinessException("当前地址不存在");
        }

        List<ProductItem> orderList = postOrderDTO.getOrderList();
        List<String> productIdList = orderList.stream().map(ProductItem::getProductId).collect(Collectors.toList());
        // 遍历orderList
        // 创建Map：productId -> OrderInfo；productId -> OrderItem
        Map<String, OrderInfo> productIdOrderInfoMap = new HashMap<>();
        Map<String, OrderItem> productIdOrderItemMap = new HashMap<>();
        Map<String, Integer> productItemCountMap = new HashMap<>();
        ProductSnapshotBatchVO snapshot = productRpcSupport.snapshotBatch(productIdList);
        Map<String, ProductInfoSnapshotVO> productInfoMap = productRpcSupport.toProductInfoMap(snapshot);
        Map<String, ProductPropertyValueSnapshotVO> productPropertyValueMap = productRpcSupport.toPropertyValueMap(snapshot);
        Map<String, ProductSkuSnapshotVO> productSkuMap = productRpcSupport.toSkuMapByPropertyValueIds(snapshot);
        // 获取当前时间
        Date now = new Date();
        List<ProductItem> newList = new ArrayList<>();
        List<OrderItem> orderItemList = new ArrayList<>();
        // 购物车列表
        List<CartDeleteItemDTO> productCartList = new ArrayList<>();
        // 物流信息
        List<OrderLogisticsInfo> orderLogisticsInfoList = new ArrayList<>();
        LogisticsSendDTO logisticsSendDTO = redisComponent.getLogisticsInfo();
        // V2 报价链路在 claim 占用时已预生成支付单号（与 order_quote.pay_order_id 绑定），
        // 普通下单仍现场生成。
        String unifiedPayOrderId = presetPayOrderId != null ? presetPayOrderId : StringTools.createPayOrderId();
        for (ProductItem productItem : orderList) {
            // 根据productId获取productInfoMap中的productInfo
            ProductInfoSnapshotVO productInfo = productInfoMap.get(productItem.getProductId());
            // 根据productId+productPropertyValueId获取productPropertyValueMap中的productPropertyValue
            // 遍历每个属性值ID，分别查询
            String[] propertyValueIdArray = productItem.getPropertyValueIds().split("-");
            List<ProductPropertyValueSnapshotVO> propertyValueList = new ArrayList<>();
            for (String propertyValueId : propertyValueIdArray) {
                ProductPropertyValueSnapshotVO pv = productPropertyValueMap.get(productItem.getProductId() + propertyValueId);
                if (pv != null) {
                    propertyValueList.add(pv);
                }
            }
            // 根据productId+productPropertyValueIds获取productSkuMap中的productSku
            ProductSkuSnapshotVO productSku = productSkuMap.get(productItem.getProductId() + productItem.getPropertyValueIds());
            // 先判断productInfo,productPropertyValue,productSku是否存在
            if (productInfo == null || !ProductStatusEnum.ON_SALE.getStatus().equals(productInfo.getStatus())) {
                throw new BusinessException("商品不存在或已下架");
            }
            if (propertyValueList.isEmpty()) {
                throw new BusinessException("商品属性不存在");
            }
            if (productSku == null) {
                throw new BusinessException("商品sku不存在");
            }
            if (productItem.getBuyCount() == null || productItem.getBuyCount() < 1
                    || productItem.getBuyCount() > Constants.ORDER_MAX_BUY_COUNT_PER_SKU) {
                throw new BusinessException("单件商品购买数量为 1~" + Constants.ORDER_MAX_BUY_COUNT_PER_SKU + " 件");
            }
            // 判断库存（真相源：smartlect_stock）；同时以服务端快照的 hash 覆盖客户端提交值
            productItem.setPropertyValueIdHash(productSku.getPropertyValueIdHash());
            int available = stockRpcSupport.getAvailable(productItem.getProductId(), productItem.getPropertyValueIdHash());
            if (available < productItem.getBuyCount()) {
                throw new BusinessException("商品【" + productInfo.getProductName() + "】库存不足");
            }

            OrderInfo orderInfo = new OrderInfo();
            // 检查当前productId的商品是否已经加入过订单，通过Map<productId,OrderInfo>
            // 新建一个OrderItem
            OrderItem orderItem = new OrderItem();
            // 若没有则新生成一个订单
            if (!productIdOrderInfoMap.containsKey(productItem.getProductId())) {
                // 将productItem中的数据赋值给orderInfo
                orderInfo.setOrderId(StringTools.createOrderId());
                // 先将amount总金额设置为0.0
                orderInfo.setAmount(new BigDecimal(Constants.ZERO_STR));
                orderInfo.setUserId(userId);
                orderInfo.setOrderTime(now);
                // 订单状态为待付款
                orderInfo.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
                orderInfo.setPayChannel(postOrderDTO.getPayMethod());
                orderInfo.setPayScene(postOrderDTO.getOrderFrom().toString());
                orderInfo.setPayOrderId(unifiedPayOrderId);
                orderInfo.setOrderItemList(new ArrayList<>());
                // 记录地址信息
                OrderLogisticsInfo orderLogisticsInfo = new OrderLogisticsInfo();
                orderLogisticsInfo.setOrderId(orderInfo.getOrderId());
                orderLogisticsInfo.setUserId(userId);
                orderLogisticsInfo.setReceiverName(userAddress.getAddressee());
                orderLogisticsInfo.setReceiverPhone(userAddress.getPhone());
                orderLogisticsInfo.setReceiverAddress(userAddress.getAddress());
                orderLogisticsInfo.setLogisticsStatus(LogisticsStatusEnum.PENDING_SHIPMENT.getStatus());
                // 设置默认发货信息:发货人、发货电话、发货地
                if (logisticsSendDTO != null) {
                    orderLogisticsInfo.setSenderName(logisticsSendDTO.getSenderName());
                    orderLogisticsInfo.setSenderPhone(logisticsSendDTO.getSenderPhone());
                    orderLogisticsInfo.setSenderAddress(logisticsSendDTO.getSenderAddress());
                }
                orderLogisticsInfoList.add(orderLogisticsInfo);
                // 将orderInfo加入到Map
                productIdOrderInfoMap.put(productItem.getProductId(), orderInfo);
            } else {
                orderInfo = productIdOrderInfoMap.get(productItem.getProductId());
            }
            // 为orderItem填充属性
            orderItem.setOrderId(orderInfo.getOrderId());
            // 获取当前商品的订单项序号
            Integer itemCount = productItemCountMap.getOrDefault(productItem.getProductId(), 0) + 1;
            productItemCountMap.put(productItem.getProductId(), itemCount);
            // 填充orderItemId，为orderId加上当前的商品数量，即为同一个productId的第几个商品
            orderItem.setOrderItemId(orderInfo.getOrderId() + "_" + itemCount);
            // 填充productId、productName、property_value_id_hash
            orderItem.setProductId(productItem.getProductId());
            orderItem.setProductName(productInfo.getProductName());
            orderItem.setPropertyValueIdHash(productSku.getPropertyValueIdHash());
            // 组装属性信息：属性名称:属性值;属性名称:属性值
            List<String> propertyData = new ArrayList<>();
            for (String propertyValueId : propertyValueIdArray) {
                ProductPropertyValueSnapshotVO productPropertyValue = productPropertyValueMap.get(productItem.getProductId() + propertyValueId);
                if (productPropertyValue != null) {
                    propertyData.add(productPropertyValue.getPropertyName() + ":" + productPropertyValue.getPropertyValue());
                }
            }
            orderItem.setPropertyInfo(String.join(";", propertyData));
            orderItem.setBuyCount(productItem.getBuyCount());
            orderItem.setItemAmount(productSku.getPrice().multiply(new BigDecimal(productItem.getBuyCount())));
            orderItem.setOrderItemStatus(OrderItemStatusEnum.NORMAL.getStatus());
            orderItem.setRemark(productItem.getRemark());
            orderItem.setRefundOrderId(null);
            String cover = null;
            // 优先取 propertyValue 中的 cover
            for (ProductPropertyValueSnapshotVO pv : propertyValueList) {
                if (!StringTools.isEmpty(pv.getPropertyCover())) {
                    cover = pv.getPropertyCover();
                    break;
                }
            }
            // 如果 propertyValue 中没有 cover，则取 productInfo 中的 cover
            if (StringTools.isEmpty(cover)) {
                cover = productInfo.getCover();
                if (!StringTools.isEmpty(cover) && cover.contains(",")) {
                    cover = cover.split(",")[0];
                }
            }
            orderItem.setCover(cover);
            productIdOrderItemMap.put(productItem.getProductId(), orderItem);
            orderInfo.setAmount(orderInfo.getAmount().add(orderItem.getItemAmount()));
            orderInfo.getOrderItemList().add(orderItem);
            orderItemList.add(orderItem);
            newList.add(productItem);
            // 如果是在购物车提交的订单，记录商品购物车信息
            if (OrderFromTypeEnum.CART == orderFromTypeEnum) {
                productCartList.add(new CartDeleteItemDTO(
                        userId,
                        productItem.getProductId(),
                        productSku.getPropertyValueIdHash(),
                        productSku.getPropertyValueIds()));
            }
        }
        String subject;
        if (OrderFromTypeEnum.CART == orderFromTypeEnum) {
            subject = String.format(Constants.CART_PAY_NAME, orderItemList.size());
        } else {
            // 直接从第一个 ProductItem 获取名称，或者从 orderItemList 获取
            subject = orderItemList.get(0).getProductName();
        }
        // 将productIdOrderInfoMap中的订单添加到orderInfoList
        List<OrderInfo> orderInfoList = new ArrayList<>(productIdOrderInfoMap.values());
        // 设置订单标题
        for (OrderInfo orderInfo : orderInfoList) {
            orderInfo.setSubject(subject);
        }

        return new PreparedOrder(payChannelEnum, orderFromTypeEnum, userAddress, newList,
                orderInfoList, orderItemList, productCartList, orderLogisticsInfoList, subject, unifiedPayOrderId, now);
    }

    private static BigDecimal total(List<OrderInfo> orders) {
        return OrderPayAmountUtil.normalizeChannelPayAmount(orders.stream().map(OrderInfo::getAmount)
                .reduce(BigDecimal.ZERO, BigDecimal::add));
    }

    // 支付表单获取是 best-effort：失败不阻塞下单（订单保持待支付，支付页可重试）。
    // userId 随契约传给 pay：Dubbo 线程没有 HTTP 上下文，取表单前的归属校验依赖
    // provider 显式注入的委托身份（2026-10-17 审计 H-1）。
    PayInfoDTO requestInitialPayInfoBestEffort(
            String payScene, String payOrderId, String subject, BigDecimal amount, String userId) {
        if (OrderPayAmountUtil.isFreeOrder(amount)) {
            return new PayInfoDTO("FREE", payOrderId, BigDecimal.ZERO.setScale(2));
        }
        try {
            return payRpcSupport.getPayUrl(payScene, payOrderId, subject, amount, userId);
        } catch (RuntimeException ex) {
            log.warn("支付表单暂不可用，订单保持待支付并允许支付页重试, payOrderId={}, error={}",
                    payOrderId, ex.getMessage());
            return new PayInfoDTO(null, payOrderId, amount);
        }
    }

    void distributeCouponDiscount(List<OrderInfo> orderInfoList, BigDecimal discount) {
        // 分摊顺序确定化（ADR-0023）：按 orderId 排序，避免 HashMap 迭代序导致同输入不同分摊
        orderInfoList.sort(java.util.Comparator.comparing(OrderInfo::getOrderId));
        BigDecimal remaining = discount;
        for (OrderInfo order : orderInfoList) {
            if (remaining.compareTo(BigDecimal.ZERO) <= 0) {
                break;
            }
            BigDecimal amt = order.getAmount() == null ? BigDecimal.ZERO : order.getAmount();
            BigDecimal off = remaining.min(amt);
            order.setAmount(amt.subtract(off).setScale(2, RoundingMode.HALF_UP));
            remaining = remaining.subtract(off);
        }
    }

    private List<ProductItem> copyItemsWithSignedBuyCount(List<ProductItem> source, boolean negate) {
        List<ProductItem> copy = new ArrayList<>(source.size());
        for (ProductItem item : source) {
            ProductItem pi = new ProductItem();
            pi.setProductId(item.getProductId());
            pi.setPropertyValueIdHash(item.getPropertyValueIdHash());
            int qty = item.getBuyCount() == null ? 0 : item.getBuyCount();
            pi.setBuyCount(negate ? -Math.abs(qty) : Math.abs(qty));
            copy.add(pi);
        }
        return copy;
    }
}
