package com.smartlect.biz;

import com.smartlect.api.dto.PostOrderDTO;
import com.smartlect.api.vo.UserAddressVO;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.utils.JsonUtils;
import com.smartlect.utils.RequestFingerprint;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class OrderQuoteServiceTest {
    private static final String JSON = """
            {"payMethod":"mock","addressId":"a1","orderFrom":0,
             "orderList":[{"productId":"p1","propertyValueIds":"v1","buyCount":1}]}
            """;

    @Test
    void inputRejectsForgedIdentityUnknownFieldsAndScalarCoercion() throws Exception {
        for (String body : List.of(JSON.replace("\"buyCount\":1", "\"buyCount\":true"),
                JSON.replace("\"buyCount\":1", "\"buyCount\":1.5"),
                JSON.replace("\"buyCount\":1", "\"buyCount\":\"1\""),
                JSON.replace("\"productId\":\"p1\"", "\"productId\":123"),
                JSON.replace("\"addressId\":\"a1\"", "\"addressId\":true"),
                JSON.replace("\"orderFrom\":0", "\"orderFrom\":0,\"userId\":\"victim\""),
                JSON.replace("\"buyCount\":1", "\"buyCount\":1,\"propertyValueIdHash\":\"forged\""))) {
            var node = JsonUtils.mapper().readTree(body);
            assertThrows(HttpBusinessException.class, () -> OrderQuoteService.parse(node, OrderQuoteService.Input.class));
        }
    }

    @Test
    void normalizationMergesSameSkuAndRejectsQuantityOverflowOrConflictingNotes() {
        OrderQuoteService.Line line = new OrderQuoteService.Line(" p1 ", "v1", 1, null);
        PostOrderDTO normalized = OrderQuoteService.normalize(new OrderQuoteService.Input(
                "mock", "a1", 0, null, List.of(line, line)));
        assertEquals(1, normalized.getOrderList().size());
        assertEquals(2, normalized.getOrderList().get(0).getBuyCount());
        assertEquals("p1", normalized.getOrderList().get(0).getProductId());
        assertThrows(HttpBusinessException.class, () -> OrderQuoteService.normalize(new OrderQuoteService.Input(
                "mock", "a1", 0, null, List.of(line, new OrderQuoteService.Line("p1", "v1", 1, "different")))));
        assertThrows(HttpBusinessException.class, () -> OrderQuoteService.normalize(new OrderQuoteService.Input(
                "mock", "a1", 0, null, List.of(new OrderQuoteService.Line("p1", "v1", Integer.MAX_VALUE, null)))));
        assertThrows(HttpBusinessException.class, () -> OrderQuoteService.normalize(new OrderQuoteService.Input(
                "retired_channel", "a1", 0, null, List.of(line))));
        assertThrows(HttpBusinessException.class, () -> OrderQuoteService.normalize(new OrderQuoteService.Input(
                "mock", "a1", 2, null, List.of(line))));
    }

    @Test
    void quoteBindsUserRequestAddressSkuPriceAndExpiration() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        OrderQuoteService service = new OrderQuoteService(jdbc,
                mock(org.springframework.transaction.PlatformTransactionManager.class));
        PostOrderDTO order = order();
        UserAddressVO address = address();
        OrderItem item = item();
        BigDecimal amount = new BigDecimal("10.00");
        Map<String, Object> result = service.issue("u1", order, address, List.of(item), amount);
        ArgumentCaptor<String> offerHash = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(anyString(), anyString(), eq("u1"), anyString(), offerHash.capture(),
                eq(1000L), any(java.sql.Timestamp.class), anyString());
        OrderQuoteService.Quote quote = new OrderQuoteService.Quote((String) result.get("quoteId"), "u1",
                RequestFingerprint.sha256(OrderQuoteService.input(order)), offerHash.getValue(), 1000,
                Instant.now().plusSeconds(60), null);
        assertDoesNotThrow(() -> service.validate(quote, "u1", order, 1000L, address, List.of(item), amount));
        assertReconfirm(() -> service.validate(quote, "u2", order, 1000L, address, List.of(item), amount));
        assertReconfirm(() -> service.validate(quote, "u1", order, 999L, address, List.of(item), amount));
        assertReconfirm(() -> service.validate(quote, "u1", order, 1000L, address, List.of(item), new BigDecimal("9.99")));
        address.setAddress("changed under same addressId");
        assertReconfirm(() -> service.validate(quote, "u1", order, 1000L, address, List.of(item), amount));
        address.setAddress("synthetic-address");
        item.setItemAmount(new BigDecimal("11.00"));
        assertReconfirm(() -> service.validate(quote, "u1", order, 1000L, address, List.of(item), amount));
        item.setItemAmount(amount);
        order.getOrderList().get(0).setBuyCount(2);
        assertReconfirm(() -> service.validate(quote, "u1", order, 1000L, address, List.of(item), amount));
        order.getOrderList().get(0).setBuyCount(1);
        OrderQuoteService.Quote expired = new OrderQuoteService.Quote(quote.quoteId(), quote.userId(),
                quote.requestHash(), quote.offerHash(), 1000, Instant.EPOCH, null);
        assertReconfirm(() -> service.validate(expired, "u1", order, 1000L, address, List.of(item), amount));
        assertFalse(JsonUtils.toJson(result).contains("synthetic-address"));
    }

    private static void assertReconfirm(org.junit.jupiter.api.function.Executable action) {
        HttpBusinessException error = assertThrows(HttpBusinessException.class, action);
        assertEquals(409, error.getHttpStatus());
        assertEquals("RECONFIRM_REQUIRED", error.getMessage());
    }

    static PostOrderDTO order() {
        return OrderQuoteService.normalize(new OrderQuoteService.Input("mock", "a1", 0, null,
                List.of(new OrderQuoteService.Line("p1", "v1", 1, null))));
    }

    static UserAddressVO address() {
        UserAddressVO address = new UserAddressVO();
        address.setAddressee("synthetic-recipient");
        address.setPhone("synthetic-phone");
        address.setAddress("synthetic-address");
        return address;
    }

    static OrderItem item() {
        OrderItem item = new OrderItem();
        item.setProductId("p1");
        item.setPropertyValueIdHash("sku1");
        item.setBuyCount(1);
        item.setItemAmount(new BigDecimal("10.00"));
        return item;
    }
}
