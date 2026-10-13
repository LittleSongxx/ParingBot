package com.smartlect.component;

import com.smartlect.api.dto.UserTempBanDTO;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 临时封禁到期自动解封：封禁时投递的定时消息（默认 2 小时）到期触发。
 */
@Slf4j
@Component
public class RabbitMQUserTempBanListenerComponent implements SmartlectMessageListener<UserTempBanDTO> {

    @Resource
    private UserTempBanService userTempBanService;

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_DELAY, RocketMqTopics.TAG_TEMPBAN_EXPIRE,
                "G_smartlect_tempban_expire");
    }

    @Override
    public Class<UserTempBanDTO> payloadType() {
        return UserTempBanDTO.class;
    }

    @Override
    public void onMessage(UserTempBanDTO dto, SmartlectMqMessage mqMessage) {
        if (dto == null || dto.getUserId() == null) {
            throw new IllegalArgumentException("临时解封消息字段不完整");
        }
        userTempBanService.tryAutoUnban(dto);
    }
}
