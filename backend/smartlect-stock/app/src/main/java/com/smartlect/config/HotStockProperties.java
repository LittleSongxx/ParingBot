package com.smartlect.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 热点库存原型配置（ADR-0010）。默认关闭；只对显式列出的 SKU 生效。
 * 配置格式：{@code smartlect.stock.hot-path.skus=productId:propertyValueIdHash,...}
 */
@Component
@ConfigurationProperties(prefix = "smartlect.stock.hot-path")
public class HotStockProperties {

    private boolean enabled;
    private List<String> skus = new ArrayList<>();
    private int buckets = 4;
    private long reservationTtlSeconds = 900;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public List<String> getSkus() {
        return skus;
    }

    public void setSkus(List<String> skus) {
        this.skus = skus;
    }

    public int getBuckets() {
        return buckets;
    }

    public void setBuckets(int buckets) {
        this.buckets = buckets;
    }

    public long getReservationTtlSeconds() {
        return reservationTtlSeconds;
    }

    public void setReservationTtlSeconds(long reservationTtlSeconds) {
        this.reservationTtlSeconds = reservationTtlSeconds;
    }
}
