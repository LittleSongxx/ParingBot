package com.smartlect.mq;

import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.client.apis.ClientConfiguration;
import org.apache.rocketmq.client.apis.ClientException;
import org.apache.rocketmq.client.apis.ClientServiceProvider;
import org.apache.rocketmq.client.apis.message.Message;
import org.apache.rocketmq.client.apis.message.MessageBuilder;
import org.apache.rocketmq.client.apis.message.MessageId;
import org.apache.rocketmq.client.apis.producer.Producer;
import org.apache.rocketmq.client.apis.producer.SendReceipt;
import org.apache.rocketmq.client.java.message.MessageBuilderImpl;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;

/**
 * RocketMQ 5.x gRPC Producer 持有者：进程内单例，同步 send 返回即 broker 确认
 * （替代原 RabbitMQ publisher-confirm 等待机制）。
 *
 * <p>endpoints 指向 RocketMQ 5.x Proxy 的 gRPC 端口（默认 8081）。5.x 客户端
 * 要求 Producer 预声明全部可能发送的 Topic（{@link RocketMqTopics#ALL_PUBLISH_TOPICS}）。</p>
 */
@Slf4j
@Component
public class RocketMqClientHolder {

    @Value("${smartlect.rocketmq.endpoints:127.0.0.1:8081}")
    private String endpoints;

    private volatile Producer producer;

    public ClientConfiguration configuration() {
        String address = (endpoints == null || endpoints.isBlank()) ? "127.0.0.1:8081" : endpoints;
        return ClientConfiguration.newBuilder()
                .setEndpoints(address)
                .setRequestTimeout(Duration.ofSeconds(10))
                .build();
    }

    /**
     * 同步发送；deliveryDelay 为 null 表示立即投递，否则按定时消息投递
     * （任意精度，取代原 TTL+死信延迟队列）。
     */
    public MessageId send(String topic, String tag, byte[] body,
                          Map<String, String> properties, Duration deliveryDelay) throws Exception {
        Producer current = obtainProducer();
        MessageBuilder builder = new MessageBuilderImpl()
                .setTopic(topic)
                .setBody(body);
        if (tag != null && !tag.isEmpty()) {
            builder.setTag(tag);
        }
        for (Map.Entry<String, String> entry : properties.entrySet()) {
            builder.addProperty(entry.getKey(), entry.getValue());
        }
        if (deliveryDelay != null && !deliveryDelay.isZero() && !deliveryDelay.isNegative()) {
            builder.setDeliveryTimestamp(System.currentTimeMillis() + deliveryDelay.toMillis());
        }
        SendReceipt receipt = current.send(builder.build());
        return receipt.getMessageId();
    }

    private Producer obtainProducer() throws ClientException {
        Producer current = producer;
        if (current != null) {
            return current;
        }
        synchronized (this) {
            if (producer == null) {
                ClientServiceProvider provider = ClientServiceProvider.loadService();
                producer = provider.newProducerBuilder()
                        .setClientConfiguration(configuration())
                        .setTopics(RocketMqTopics.ALL_PUBLISH_TOPICS.toArray(new String[0]))
                        .build();
                log.info("RocketMQ Producer 已启动 endpoints={}", endpoints);
            }
            return producer;
        }
    }

    @PreDestroy
    public void shutdown() throws IOException {
        Producer current = producer;
        if (current != null) {
            current.close();
            log.info("RocketMQ Producer 已关闭");
        }
    }
}
