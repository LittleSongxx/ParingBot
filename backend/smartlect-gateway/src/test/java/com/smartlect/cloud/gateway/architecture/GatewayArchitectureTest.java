package com.smartlect.cloud.gateway.architecture;

import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

/** 网关只做路由/鉴权/限流，不依赖任何业务域实现。 */
@AnalyzeClasses(packages = "com.smartlect.cloud.gateway")
class GatewayArchitectureTest {

    @ArchTest
    static final ArchRule gateway_does_not_depend_on_business_implementation =
            noClasses().that().resideInAPackage("com.smartlect.cloud.gateway..")
                    .should().dependOnClassesThat().resideInAnyPackage(
                            "com.smartlect.controller..",
                            "com.smartlect.biz..",
                            "com.smartlect.mappers..",
                            "com.smartlect.service..",
                            "com.smartlect.task..");
}
