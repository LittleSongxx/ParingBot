export const TRIAL_GALLERY = {
  account: 'gallery',
  password: 'Visit-Smartlect-2026',
  label: '作品集展厅'
}

export const TRIAL_ADMIN_DENIED = '作品集展厅账号只能查看看板、商品、订单和知识库，不能改库存、发知识、发券或查看用户隐私。'

// 券管理页：读接口已放开给展厅（写仍仅超管，且被 TrialAdminAccess 拒绝清单再挡一次）


export const TRIAL_MENU_PATHS = new Set([
  '/home',
  '/product',
  '/product/category',
  '/product/ProductProperty',
  '/order/orderList',
  '/order/report',
  '/order/refundReview',
  '/discountCoupon',
  '/merchant',
  '/ads',
  '/knowledge',
  '/reviewAnalysis',
  '/growthReport',
  '/setting/logistics',
  '/ai/models',
  '/ai/prompts',
  '/ai/knowledge-index',
  '/ai/runs'
])
