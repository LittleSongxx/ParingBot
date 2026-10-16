package com.smartlect.security;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 展厅账号（TRIAL_OPERATOR）的<b>显式放宽</b>标记：方法上标注即放行，优先于
 * {@link TrialAdminAccess} 的策略判定（读默认允许 / 写默认拒绝 / 隐私清单拒绝）。
 *
 * <p>历史提示：本注解此前只有文档没有消费者（"Deny-by-default otherwise" 从未生效），
 * 2026-10-16 审计实测发现展厅账号可直接调发货等写接口后，才补上
 * {@code TrialAdminGuardInterceptor} 作为它的唯一消费者。新增放行请用本注解，
 * 不要再往策略里堆路径。</p>
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface TrialReadable {
}
