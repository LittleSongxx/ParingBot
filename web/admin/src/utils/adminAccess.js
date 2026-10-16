import { TRIAL_MENU_PATHS } from '@/constants/trial'

export const ADMIN_PERMISSION = Object.freeze({
  AI_EVALUATE: 'ai:evaluate',
  AI_PILOT: 'ai:pilot',
  ANALYTICS_READ: 'analytics:read',
  ANALYTICS_EXPORT: 'analytics:export',
  AUDIT_READ: 'audit:read',
  ADMIN_TRIAL: 'admin:trial',
})

export function normalizeAdminPrincipal(value) {
  const principal = value && typeof value === 'object' ? value : {}
  return {
    ...principal,
    roles: Array.isArray(principal.roles) ? principal.roles : [],
    permissions: Array.isArray(principal.permissions) ? principal.permissions : [],
  }
}

export function hasAdminPermission(principal, permission) {
  return normalizeAdminPrincipal(principal).permissions.includes(permission)
}

export function hasAnyAdminPermission(principal, permissions) {
  const granted = new Set(normalizeAdminPrincipal(principal).permissions)
  return permissions.some((permission) => granted.has(permission))
}

export function isTrialAdmin(principal) {
  // 与后端 TrialIdentities.isTrialAdmin 同一口径：超管持有全部权限点（含 admin:trial），
  // 只看权限点会把超管误判成展厅（2026-10-17 审计 H2——后端已修，这里是 JS 孪生）。
  const current = normalizeAdminPrincipal(principal)
  if (String(current.account || '').toLowerCase() === 'gallery') {
    return true
  }
  if (current.roles.includes('TRIAL_OPERATOR')) {
    return true
  }
  return current.permissions.includes(ADMIN_PERMISSION.ADMIN_TRIAL)
    && !current.permissions.includes('admin:legacy')
    && !current.roles.includes('SUPER_ADMIN')
}

export function filterTrialMenu(items) {
  return items
    .map((item) => {
      if (item.children) {
        const children = item.children.filter((child) => TRIAL_MENU_PATHS.has(child.path))
        return children.length ? { ...item, children } : null
      }
      return TRIAL_MENU_PATHS.has(item.path) ? item : null
    })
    .filter(Boolean)
}
