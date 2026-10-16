import { describe, expect, it } from 'vitest'
import { filterTrialMenu, isTrialAdmin } from '@/utils/adminAccess'

const principal = (roles, permissions, account) => ({ roles, permissions, account })

// 与后端 TrialIdentities.isTrialAdmin 同口径：超管持有全部权限点（含 admin:trial），
// 只看权限点会把超管误判成展厅（2026-10-17 审计 H2 的回归网）。
describe('isTrialAdmin（展厅身份判定）', () => {
  it('固定账号 gallery 直接成立', () => {
    expect(isTrialAdmin(principal([], ['admin:trial'], 'gallery'))).toBe(true)
  })

  it('TRIAL_OPERATOR 角色是排他标识', () => {
    expect(isTrialAdmin(principal(['TRIAL_OPERATOR'], [], 'whatever'))).toBe(true)
  })

  it('超管持有 admin:trial / admin:legacy 时不得被判为展厅', () => {
    expect(
      isTrialAdmin(principal(['SUPER_ADMIN'], ['admin:trial', 'admin:legacy', 'admin:manage'], 'admin')),
    ).toBe(false)
  })

  it('带 admin:legacy 的普通管理员同样不是展厅', () => {
    expect(isTrialAdmin(principal([], ['admin:trial', 'admin:legacy'], 'ops'))).toBe(false)
  })

  it('纯 admin:trial 权限（无 legacy/超管）仍判为展厅', () => {
    expect(isTrialAdmin(principal([], ['admin:trial'], 'someone'))).toBe(true)
  })

  it('缺字段/null 输入按非展厅处理（不影响正常账号）', () => {
    expect(isTrialAdmin(null)).toBe(false)
    expect(isTrialAdmin({ roles: ['SUPER_ADMIN'], permissions: ['admin:trial'] })).toBe(false)
  })
})

describe('filterTrialMenu（展厅菜单过滤）', () => {
  it('只保留 TRIAL_MENU_PATHS 内的路径，空 children 的父项被剔除', () => {
    const menu = [
      { path: '/home' },
      { path: '/ai/models' },
      { path: '/secret', children: [{ path: '/secret/x' }] },
      { path: '/product', children: [{ path: '/product/category' }, { path: '/secret/x' }] },
    ]
    const filtered = filterTrialMenu(menu)
    expect(filtered.map((item) => item.path)).toEqual(['/home', '/ai/models', '/product'])
    expect(filtered[2].children.map((child) => child.path)).toEqual(['/product/category'])
  })
})
