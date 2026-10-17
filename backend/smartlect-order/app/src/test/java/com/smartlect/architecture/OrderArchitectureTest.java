package com.smartlect.architecture;

import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

/** API 契约是跨服务边界：不能反向依赖任何服务的 controller/biz/mapper/state 实现。 */
@AnalyzeClasses(packages = "com.smartlect.api")
class OrderArchitectureTest {

    @ArchTest
    static final ArchRule api_contract_does_not_depend_on_service_internals =
            noClasses().that().resideInAPackage("com.smartlect.api..")
                    .should().dependOnClassesThat().resideInAnyPackage(
                            "com.smartlect.controller..",
                            "com.smartlect.biz..",
                            "com.smartlect.mappers..",
                            "com.smartlect.state..",
                            "com.smartlect.component..",
                            "com.smartlect.task..");
}
