package com.smartlect.config;

import org.junit.jupiter.api.Test;
import org.slf4j.MDC;

import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/** MDC 异步传播（ADR-0021）：提交线程的 traceId 在异步任务内可见，结束后清理。 */
class MdcTaskDecoratorTest {

    @Test
    void copiesMdcIntoTaskAndRestoresAfterwards() throws Exception {
        MDC.put("traceId", "trace-abc");
        AtomicReference<String> inTask = new AtomicReference<>();
        Thread worker = new Thread(new MdcTaskDecorator().decorate(() -> inTask.set(MDC.get("traceId"))));
        try {
            MDC.put("traceId", "trace-abc");
            worker.start();
            worker.join(5000);
            assertEquals("trace-abc", inTask.get());
        } finally {
            MDC.remove("traceId");
        }
    }

    @Test
    void clearsMdcWhenSubmitContextHadNone() throws Exception {
        AtomicReference<String> inTask = new AtomicReference<>("sentinel");
        Thread worker = new Thread(new MdcTaskDecorator().decorate(() -> inTask.set(MDC.get("traceId"))));
        worker.start();
        worker.join(5000);
        assertNull(inTask.get());
    }
}
