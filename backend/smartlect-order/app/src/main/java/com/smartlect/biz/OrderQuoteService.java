package com.smartlect.biz;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.smartlect.api.dto.PostOrderDTO;
import com.smartlect.api.vo.UserAddressVO;
import com.smartlect.constants.Constants;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.ProductItem;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.utils.JsonUtils;
import com.smartlect.utils.RequestFingerprint;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;
import java.util.UUID;

/** Java-issued, single-use quotes. The surrounding order transaction owns consumption. */
@Service
public class OrderQuoteService {
    private static final ObjectMapper STRICT = JsonMapper.builder()
            .disable(MapperFeature.ALLOW_COERCION_OF_SCALARS)
            .disable(DeserializationFeature.ACCEPT_FLOAT_AS_INT)
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES).build();
    static {
        STRICT.coercionConfigFor(com.fasterxml.jackson.databind.type.LogicalType.Textual)
                .setCoercion(com.fasterxml.jackson.databind.cfg.CoercionInputShape.Integer,
                        com.fasterxml.jackson.databind.cfg.CoercionAction.Fail)
                .setCoercion(com.fasterxml.jackson.databind.cfg.CoercionInputShape.Float,
                        com.fasterxml.jackson.databind.cfg.CoercionAction.Fail)
                .setCoercion(com.fasterxml.jackson.databind.cfg.CoercionInputShape.Boolean,
                        com.fasterxml.jackson.databind.cfg.CoercionAction.Fail);
    }
    private final JdbcTemplate jdbc;
    private final TransactionTemplate claimTx;

    public OrderQuoteService(JdbcTemplate jdbc, PlatformTransactionManager transactionManager) {
        this.jdbc = jdbc;
        this.claimTx = new TransactionTemplate(transactionManager);
    }

    public record Line(String productId, String propertyValueIds, Integer buyCount, String remark) { }
    public record Input(String payMethod, String addressId, Integer orderFrom,
                        String userCouponId, List<Line> orderList) { }
    public record Confirmed(String quoteId, Long confirmedAmountCents, Input order) { }
    public record Quote(String quoteId, String userId, String requestHash, String offerHash,
                        long amountCents, Instant expiresAt, String payOrderId) { }

    public static <T> T parse(JsonNode json, Class<T> type) {
        try {
            if (json == null || !json.isObject()) throw new IllegalArgumentException();
            return STRICT.treeToValue(json, type);
        } catch (Exception invalid) {
            throw new HttpBusinessException(400, "INVALID_CHECKOUT_ARGUMENTS");
        }
    }

    public static PostOrderDTO normalize(Input input) {
        if (input == null || input.orderFrom() == null || input.orderList() == null
                || input.orderList().isEmpty() || input.orderList().size() > 50) invalid();
        if (input.orderFrom() != 0 && input.orderFrom() != 1) invalid();
        PostOrderDTO dto = new PostOrderDTO();
        dto.setPayMethod(required(input.payMethod(), 32));
        if (!"mock".equals(dto.getPayMethod())) {
            throw new HttpBusinessException(400, "ONLY_SIMULATED_PAYMENT_SUPPORTED");
        }
        dto.setAddressId(required(input.addressId(), 64));
        dto.setOrderFrom(input.orderFrom());
        dto.setUserCouponId(optional(input.userCouponId(), 64));
        Map<String, ProductItem> items = new TreeMap<>();
        for (Line line : input.orderList()) {
            if (line == null || line.buyCount() == null || line.buyCount() < 1
                    || line.buyCount() > Constants.ORDER_MAX_BUY_COUNT_PER_SKU) invalid();
            String productId = required(line.productId(), 64);
            String properties = required(line.propertyValueIds(), 512);
            String remark = optional(line.remark(), 500);
            String key = productId + "\0" + properties;
            ProductItem item = items.get(key);
            if (item == null) {
                item = new ProductItem();
                item.setProductId(productId);
                item.setPropertyValueIds(properties);
                item.setBuyCount(line.buyCount());
                item.setRemark(remark);
                items.put(key, item);
            } else {
                if (!Objects.equals(item.getRemark(), remark)) invalid();
                int count = Math.addExact(item.getBuyCount(), line.buyCount());
                if (count > Constants.ORDER_MAX_BUY_COUNT_PER_SKU) invalid();
                item.setBuyCount(count);
            }
        }
        dto.setOrderList(new ArrayList<>(items.values()));
        return dto;
    }

    public static Input input(PostOrderDTO dto) {
        return new Input(dto.getPayMethod(), dto.getAddressId(), dto.getOrderFrom(),
                dto.getUserCouponId(), dto.getOrderList().stream().map(item -> new Line(
                        item.getProductId(), item.getPropertyValueIds(), item.getBuyCount(), item.getRemark())).toList());
    }

    public Map<String, Object> issue(String userId, PostOrderDTO order, UserAddressVO address,
                                   List<OrderItem> items, BigDecimal total) {
        String id = UUID.randomUUID().toString().replace("-", "");
        Instant expires = Instant.now().plusSeconds(300);
        String requestHash = RequestFingerprint.sha256(input(order));
        long cents = cents(total);
        jdbc.update("""
                INSERT INTO order_quote
                (quote_id,user_id,request_hash,offer_hash,amount_cents,expires_at,request_json)
                VALUES (?,?,?,?,?,?,?)
                """, id, userId, requestHash, offerHash(address, items, total), cents,
                Timestamp.from(expires), JsonUtils.toJson(input(order)));
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("quoteId", id);
        result.put("requestHash", requestHash);
        result.put("totalAmountCents", cents);
        result.put("expiresAt", expires.toString());
        result.put("order", input(order));
        return result;
    }

    public Quote lock(String userId, String quoteId) {
        if (quoteId == null || !quoteId.matches("[a-f0-9]{32}")) reconfirm();
        List<Quote> rows = jdbc.query("""
                SELECT quote_id,user_id,request_hash,offer_hash,amount_cents,expires_at,pay_order_id
                FROM order_quote WHERE quote_id=? AND user_id=? FOR UPDATE
                """, (row, number) -> new Quote(row.getString("quote_id"), row.getString("user_id"),
                row.getString("request_hash"), row.getString("offer_hash"), row.getLong("amount_cents"),
                row.getTimestamp("expires_at").toInstant(), row.getString("pay_order_id")), quoteId, userId);
        if (rows.isEmpty()) reconfirm();
        Quote quote = rows.get(0);
        if (quote.payOrderId() != null) throw new HttpBusinessException(409, "QUOTE_ALREADY_CONSUMED");
        return quote;
    }

    public void validate(Quote quote, String userId, PostOrderDTO order, Long confirmedAmountCents,
                         UserAddressVO address, List<OrderItem> items, BigDecimal total) {
        validateRequest(quote, userId, order, confirmedAmountCents);
        if (quote.amountCents() != cents(total) || !quote.offerHash().equals(offerHash(address, items, total))) reconfirm();
    }

    public void validateRequest(Quote quote, String userId, PostOrderDTO order, Long confirmedAmountCents) {
        if (quote == null || !quote.userId().equals(userId) || confirmedAmountCents == null
                || quote.amountCents() != confirmedAmountCents
                || !quote.expiresAt().isAfter(Instant.now())
                || !quote.requestHash().equals(RequestFingerprint.sha256(input(order)))) reconfirm();
    }

    public void consume(Quote quote, String payOrderId) {
        if (jdbc.update("UPDATE order_quote SET pay_order_id=? WHERE quote_id=? AND user_id=? AND pay_order_id IS NULL",
                payOrderId, quote.quoteId(), quote.userId()) != 1) {
            throw new HttpBusinessException(409, "QUOTE_ALREADY_CONSUMED");
        }
    }

    /**
     * claim-first 短事务占用（ADR-0002）：在行锁事务内完成 校验 + 一次性占用。
     * 旧实现 lock 的 FOR UPDATE 脱离事务上下文即释放、consume 又发生在建单副作用之后，
     * 并发重复请求会先落单再被 409 挡下，留下无支付意图的孤儿订单。
     * 现在占用发生在任何建单副作用之前；失败用 {@link #release} 逆向释放。
     */
    public Quote claim(String userId, String quoteId, String payOrderId, PostOrderDTO order, Long confirmedAmountCents) {
        return claimTx.execute(status -> {
            Quote locked = lock(userId, quoteId);
            validateRequest(locked, userId, order, confirmedAmountCents);
            consume(locked, payOrderId);
            return locked;
        });
    }

    /** 建单失败时释放占用：仅当占用者仍是本请求的 payOrderId 才回滚为可下单。 */
    public boolean release(String quoteId, String userId, String claimedPayOrderId) {
        return jdbc.update("""
                UPDATE order_quote SET pay_order_id=NULL
                WHERE quote_id=? AND user_id=? AND pay_order_id=?
                """, quoteId, userId, claimedPayOrderId) == 1;
    }

    private static String offerHash(UserAddressVO address, List<OrderItem> items, BigDecimal total) {
        List<Map<String, Object>> lines = items.stream().sorted(Comparator.comparing(OrderItem::getProductId)
                .thenComparing(OrderItem::getPropertyValueIdHash)).map(item -> Map.<String, Object>of(
                "productId", item.getProductId(), "sku", item.getPropertyValueIdHash(),
                "quantity", item.getBuyCount(), "grossCents", cents(item.getItemAmount()))).toList();
        // Only the digest persists: a changed address under the same addressId also needs confirmation.
        return RequestFingerprint.sha256(Map.of("lines", lines, "totalCents", cents(total),
                "receiver", List.of(Objects.toString(address.getAddressee(), ""),
                        Objects.toString(address.getPhone(), ""), Objects.toString(address.getAddress(), ""))));
    }

    public static long cents(BigDecimal amount) {
        if (amount == null || amount.signum() < 0) invalid();
        try { return amount.movePointRight(2).longValueExact(); }
        catch (ArithmeticException invalid) { throw new HttpBusinessException(400, "INVALID_MONEY"); }
    }

    private static String required(String value, int limit) {
        String result = optional(value, limit);
        if (result == null) invalid();
        return result;
    }

    private static String optional(String value, int limit) {
        if (value == null || value.isBlank()) return null;
        String result = value.trim();
        if (result.length() > limit || result.chars().anyMatch(c -> c < 32 || c == 127)) invalid();
        return result;
    }

    private static void invalid() { throw new HttpBusinessException(400, "INVALID_CHECKOUT_ARGUMENTS"); }
    public static void reconfirm() { throw new HttpBusinessException(409, "RECONFIRM_REQUIRED"); }
}
