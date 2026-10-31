import { test, expect } from '@playwright/test'
import { ADMIN, MEMBER, loginViaApi } from './helpers.js'

test.describe('只读接口契约（readiness / 管理端列表）', () => {
  test('member01 readiness 字段完整，并给出可运行或阻断状态', async ({ request }) => {
    const member = await loginViaApi(request, MEMBER)
    const response = await request.get('/api/match/my', {
      headers: { token: member.token }
    })
    expect(response.ok()).toBeTruthy()

    const body = await response.json()
    expect(body.code).toBe('200')

    // readiness 不得把 API Key 之类的敏感字段透出给租客端
    const serialized = JSON.stringify(body)
    expect(serialized).not.toContain('api_key')
    expect(serialized).not.toMatch(/sk-[A-Za-z0-9]/)

    const readiness = body.data.readiness
    expect(Array.isArray(readiness.checks)).toBeTruthy()
    expect(readiness.checks.length).toBeGreaterThan(0)
    expect(typeof readiness.can_run).toBe('boolean')

    for (const check of readiness.checks) {
      expect(typeof check.key).toBe('string')
      expect(check.key.length).toBeGreaterThan(0)
      expect(typeof check.label).toBe('string')
      expect(check.label.length).toBeGreaterThan(0)
      expect(typeof check.ok).toBe('boolean')
      expect(typeof check.message).toBe('string')
      expect(check.message.length).toBeGreaterThan(0)
    }

    const keys = readiness.checks.map((check) => check.key)
    expect(keys).toEqual(
      expect.arrayContaining(['profile', 'intro', 'preference', 'moment', 'model'])
    )

    if (readiness.blocker) {
      expect(readiness.can_run).toBe(false)
      expect(readiness.blocker.ok).toBe(false)
      expect(keys).toContain(readiness.blocker.key)
      expect(readiness.checks[readiness.checks.length - 1].key).toBe(
        readiness.blocker.key
      )
    } else {
      expect(readiness.can_run).toBe(true)
      expect(keys).toContain('chat')

      // 租期匹配候选检查：member01 有计划租期，可运行时必须算出候选池。
      const leaseCheck = readiness.checks.find((check) => check.key === 'lease_pool')
      expect(leaseCheck).toBeTruthy()
      expect(leaseCheck.ok).toBe(true)
      expect(leaseCheck.message).toMatch(/\d+ 位可能进入匹配的候选/)
    }
  })

  test('无 Key 的全新种子栈应以模型配置阻断 readiness（本机有 Key 时跳过）', async ({
    request
  }) => {
    const member = await loginViaApi(request, MEMBER)
    const response = await request.get('/api/match/my', {
      headers: { token: member.token }
    })
    const body = await response.json()
    const readiness = body.data.readiness

    // 本地联调栈可能已经配置了真实 Key；CI 是全新种子库，
    // 四条 ai_model_config 的 api_key 都是 NULL，必须命中「调度模型」阻断。
    if (readiness.blocker === null) {
      test.skip(
        !process.env.CI,
        '本机联调栈已配置 API Key；「无 Key」的页面文案由 tenant.spec.js 的接口桩用例覆盖'
      )
    }
    expect(
      readiness.blocker,
      'CI 全新种子库应保持 ai_model_config.api_key 为 NULL，否则无 Key 阻断路径失去覆盖'
    ).not.toBeNull()

    expect(readiness.blocker.key).toBe('model')
    expect(readiness.blocker.ok).toBe(false)
    expect(readiness.blocker.message).toContain('还没有填写 API Key')
    expect(readiness.blocker.message).toContain('AI模型配置')
    expect(readiness.can_run).toBe(false)
  })

  test('admin 用户与参数列表接口可用，且不返回密码字段', async ({ request }) => {
    const admin = await loginViaApi(request, ADMIN)

    const users = await request.get('/api/user/selectPage?page_num=1&page_size=5', {
      headers: { token: admin.token }
    })
    expect(users.ok()).toBeTruthy()
    const userBody = await users.json()
    expect(userBody.code).toBe('200')
    expect(userBody.data.total).toBeGreaterThanOrEqual(3)
    expect(userBody.data.list).toHaveLength(5)
    for (const user of userBody.data.list) {
      expect(user).not.toHaveProperty('password')
    }

    const configs = await request.get(
      '/api/sysConfig/selectPage?page_num=1&page_size=10',
      { headers: { token: admin.token } }
    )
    expect(configs.ok()).toBeTruthy()
    const configBody = await configs.json()
    expect(configBody.code).toBe('200')
    expect(configBody.data.total).toBe(7)
    expect(configBody.data.list.map((item) => item.config_key)).toContain(
      'SUPERVISOR_MAX_ROUND'
    )
  })

  test('未登录访问受保护接口返回业务码 401', async ({ request }) => {
    const response = await request.get('/api/match/my')
    const body = await response.json()
    expect(body.code).toBe('401')
  })
})

