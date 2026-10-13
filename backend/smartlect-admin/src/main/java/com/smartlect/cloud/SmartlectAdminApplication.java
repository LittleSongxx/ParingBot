package com.smartlect.cloud;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.context.annotation.FullyQualifiedAnnotationBeanNameGenerator;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableDiscoveryClient
@org.apache.dubbo.config.spring.context.annotation.EnableDubbo(scanBasePackages = "com.smartlect")
@ComponentScan(basePackages = "com.smartlect", nameGenerator = FullyQualifiedAnnotationBeanNameGenerator.class)
@MapperScan("com.smartlect.mappers")
@EnableScheduling
public class SmartlectAdminApplication {
    public static void main(String[] args) {
        SpringApplication.run(SmartlectAdminApplication.class, args);
    }
}
