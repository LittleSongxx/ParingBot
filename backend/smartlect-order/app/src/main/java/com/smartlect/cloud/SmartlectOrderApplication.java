package com.smartlect.cloud;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.context.annotation.FullyQualifiedAnnotationBeanNameGenerator;

@SpringBootApplication
@EnableDiscoveryClient
@org.apache.dubbo.config.spring.context.annotation.EnableDubbo(scanBasePackages = "com.smartlect")
@ComponentScan(basePackages = "com.smartlect", nameGenerator = FullyQualifiedAnnotationBeanNameGenerator.class)
@MapperScan("com.smartlect.mappers")
// 注意：曾在此加过 @EnableAspectJAutoProxy(exposeProxy = true) 想给
// AopContext.currentProxy() 开路，但实测无效——它与 Boot 的 AopAutoConfiguration
// 存在注册时序问题，注解在、代理也生效，AopContext 仍为 null。
// 需要"回发后再自调用"的消费者改用 @Lazy 自注入（见 ConfirmReceiptListener.self、
// LogisticsStepListener.self），不依赖这个全局开关，因此这里不再保留该注解。
public class SmartlectOrderApplication {
    public static void main(String[] args) {
        SpringApplication.run(SmartlectOrderApplication.class, args);
    }
}
