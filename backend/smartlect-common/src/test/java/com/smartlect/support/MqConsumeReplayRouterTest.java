package com.smartlect.support;

import com.smartlect.mq.RocketMqTopics;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class MqConsumeReplayRouterTest {

    @Test
    void newLogicalQueueFormResolvesToTopicAndTag() {
        assertEquals(
                new MqConsumeReplayRouter.Target(RocketMqTopics.TOPIC_REFUND, RocketMqTopics.TAG_REFUND_STOCK),
                MqConsumeReplayRouter.resolve("smartlect-refund:refund-stock"));
        assertEquals(
                new MqConsumeReplayRouter.Target(RocketMqTopics.TOPIC_PAY, RocketMqTopics.TAG_PAY_SUCCESS),
                MqConsumeReplayRouter.resolve("smartlect-pay:pay-success"));
    }

    @Test
    void legacyRabbitQueueNamesStillResolveAfterMigration() {
        assertEquals(
                new MqConsumeReplayRouter.Target(RocketMqTopics.TOPIC_REFUND, RocketMqTopics.TAG_REFUND_STOCK),
                MqConsumeReplayRouter.resolve("smartlect.refund.stock.queue"));
        assertEquals(
                new MqConsumeReplayRouter.Target(RocketMqTopics.TOPIC_REFUND, RocketMqTopics.TAG_REFUND_RESULT),
                MqConsumeReplayRouter.resolve("smartlect.refund.result.queue"));
        assertEquals(
                new MqConsumeReplayRouter.Target(RocketMqTopics.TOPIC_RUSH, RocketMqTopics.TAG_RUSH_ORDER),
                MqConsumeReplayRouter.resolve("smartlect.rushing.order.queue"));
        assertEquals(
                new MqConsumeReplayRouter.Target(RocketMqTopics.TOPIC_DELAY, RocketMqTopics.TAG_TEMPBAN_EXPIRE),
                MqConsumeReplayRouter.resolve("smartlect.user.tempban.dead.queue"));
    }

    @Test
    void unknownQueueCannotBeReplayed() {
        assertNull(MqConsumeReplayRouter.resolve("unknown.queue"));
    }
}
