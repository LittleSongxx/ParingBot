import { expect } from '@playwright/test'

export const USER_CACHE_KEY = 'xm-user'

// 演示账号固定为种子数据里的 admin / member01。
// member02 在本地联调时可能正在跑真实匹配，E2E 一律不碰它。
export const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME || 'admin',
  password: process.env.E2E_ADMIN_PASSWORD || 'admin123'
}

export const MEMBER = {
  username: process.env.E2E_MEMBER_USERNAME || 'member01',
  password: process.env.E2E_MEMBER_PASSWORD || '123456'
}

export const MEMBER_NAME = '小宋'

// 只用于拦截 /api/match/my 的页面状态用例：不登录后端也能渲染页面。
export const STUB_MEMBER = {
  id: 2,
  username: 'member01',
  name: MEMBER_NAME,
  role: 'USER',
  status: 'NORMAL',
  token: 'e2e-stub-token'
}

export async function loginViaApi(request, credentials = MEMBER) {
  const response = await request.post('/api/login', { data: credentials })
  const body = await response.json().catch(() => ({}))
  expect(response.ok(), `登录接口 HTTP ${response.status()}：${JSON.stringify(body)}`).toBeTruthy()
  expect(body.code, `登录失败：${body.msg || '未知错误'}`).toBe('200')
  return body.data
}

export async function seedSession(page, user) {
  await page.addInitScript(
    ({ key, value }) => {
      window.localStorage.setItem(key, value)
    },
    { key: USER_CACHE_KEY, value: JSON.stringify(user) }
  )
}

export async function openAs(page, request, path, credentials = MEMBER) {
  const user = await loginViaApi(request, credentials)
  await seedSession(page, user)
  await page.goto(path)
  return user
}

// 关键断言：模板里的未定义值不能被直接渲染到页面上。
export async function expectNoPlaceholderLeak(page) {
  const text = await page.locator('body').innerText()
  expect(text, '页面不应把 undefined 渲染给用户').not.toMatch(/\bundefined\b/)
  expect(text, '页面不应把 NaN 渲染给用户').not.toMatch(/\bNaN\b/)
}

export function readinessCheck(key, label, ok, message, actionPath = null, actionLabel = null) {
  return {
    key,
    label,
    ok,
    message,
    action_path: actionPath,
    action_label: actionLabel
  }
}

// 与后端 /match/my 返回结构保持一致的最小页面数据。
export function matchPageData(overrides = {}) {
  const base = {
    has_profile: true,
    readiness: { checks: [], blocker: null, can_run: false },
    task: null,
    run: null,
    rounds: [],
    counts: { total: 0, passed: 0, rejected: 0, pending: 0 },
    distribution: [],
    limits: { round_limit: 12, relax_limit: 3, portrait_limit: 2 },
    note: null,
    delivered: 0
  }
  return {
    ...base,
    ...overrides,
    readiness: { ...base.readiness, ...(overrides.readiness || {}) },
    counts: { ...base.counts, ...(overrides.counts || {}) },
    limits: { ...base.limits, ...(overrides.limits || {}) }
  }
}

export async function stubMatchApi(page, data, { status = 200 } = {}) {
  await page.route('**/api/match/my', async (route) => {
    if (status !== 200) {
      await route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'e2e simulated server error' })
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: '200', msg: '请求成功', data })
    })
  })
}
