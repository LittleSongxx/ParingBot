package com.smartlect.config;

import org.slf4j.MDC;
import org.springframework.core.task.TaskDecorator;

import java.util.Map;

/**
 * MDC 传播装饰器（ADR-0009）：异步线程池此前不复制 MDC，traceId 在异步边界断裂。
 * 提交时快照提交线程的 MDC、执行时替换、结束后清理。
 */
public class MdcTaskDecorator implements TaskDecorator {

    @Override
    public Runnable decorate(Runnable runnable) {
        Map<String, String> context = MDC.getCopyOfContextMap();
        return () -> {
            Map<String, String> previous = MDC.getCopyOfContextMap();
            if (context != null) {
                MDC.setContextMap(context);
            } else {
                MDC.clear();
            }
            try {
                runnable.run();
            } finally {
                if (previous != null) {
                    MDC.setContextMap(previous);
                } else {
                    MDC.clear();
                }
            }
        };
    }
}
