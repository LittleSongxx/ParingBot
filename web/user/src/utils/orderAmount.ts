import { couponTypeLabel } from '@/constants/backendEnums';

/**
 * 金额展示：null / undefined / 空串 显示为 "—" 而不是 0.00。
 *
 * 2026-10-16 审计：`Number(val ?? 0).toFixed(2)` 会把"后端没给这个字段"画成 ¥0.00，
 * 用户与客服都可能把它当成真实金额（与"金额以服务端为准"的承诺冲突）。
 */
export const formatOrderMoney = (val: unknown) =>
  val === null || val === undefined || val === '' ? '—' : Number(val).toFixed(2);

export const hasOrderCouponDiscount = (order?: Record<string, any> | null) =>
  Number(order?.couponDiscountAmount ?? 0) > 0;

export const orderCouponTypeText = (order?: Record<string, any> | null) =>
  order?.couponType != null ? couponTypeLabel(order.couponType) : '';

export const orderCouponSummaryText = (order?: Record<string, any> | null) => {
  if (!hasOrderCouponDiscount(order)) return '';
  const name = order?.couponName ? String(order.couponName) : '优惠券';
  const type = orderCouponTypeText(order);
  return type ? `${name}（${type}）` : name;
};
