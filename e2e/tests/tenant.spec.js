import { test, expect } from './fixtures.js'
import {
  MEMBER,
  MEMBER_NAME,
  STUB_MEMBER,
  expectNoPlaceholderLeak,
  loginViaApi,
  matchPageData,
  openAs,
  readinessCheck,
  seedSession,
  stubMatchApi
} from './helpers.js'

test.describe('租客端页面（member01，只读）', () => {
  test('首页正常渲染并显示当前登录租客', async ({ page, request }) => {
    await openAs(page, request, '/front/home', MEMBER)

    await expect(page).toHaveURL(/\/front\/home$/)
    await expect(page.getByRole('heading', { name: /把找室友/ })).toBeVisible()
    await expect(page.getByText('我的功能', { exact: true })).toBeVisible()
    await expect(page.locator('.front-user-chip .user-name')).toHaveText(MEMBER_NAME)
    await expectNoPlaceholderLeak(page)
  })

  test('租客档案展示已审核资料', async ({ page, request }) => {
    await openAs(page, request, '/front/memberProfile', MEMBER)

    await expect(page.getByRole('heading', { name: '租客档案' })).toBeVisible()
    await expect(
      page.getByPlaceholder('展示在档案卡上的名字，可以不写真名')
    ).toHaveValue(MEMBER_NAME)
    await expect(page.getByText('档案审核状态', { exact: true })).toBeVisible()
    await expect(page.getByText('档案已通过审核', { exact: true })).toBeVisible()
    await expect(page.getByText(/审核状态：/)).toBeVisible()
    await expectNoPlaceholderLeak(page)
  })

  test('合住偏好展示七个维度与必须项计数', async ({ page, request }) => {
    await openAs(page, request, '/front/myPreference', MEMBER)

    await expect(page.getByRole('heading', { name: '合住偏好' })).toBeVisible()
    await expect(page.getByText('七个维度', { exact: true })).toBeVisible()
    await expect(page.locator('.dim-card')).toHaveCount(7)
    await expect(page.getByText(/已标「必须」/)).toBeVisible()
    await expectNoPlaceholderLeak(page)
  })

  test('智能匹配展示真实 readiness 与任务信息，且不触发 rerun', async ({ page, request }) => {
    const member = await loginViaApi(request, MEMBER)
    await seedSession(page, member)

    let rerunCalls = 0
    page.on('request', (request) => {
      if (request.url().includes('/api/match/rerun')) rerunCalls += 1
    })

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes('/api/match/my') &&
        response.request().method() === 'GET'
    )
    await page.goto('/front/myMatch')
    const response = await responsePromise
    expect(response.ok()).toBeTruthy()

    const data = (await response.json()).data
    expect(Array.isArray(data.readiness.checks)).toBeTruthy()
    expect(data.readiness.checks.length).toBeGreaterThan(0)

    await expect(page.getByRole('heading', { name: '智能匹配' })).toBeVisible()
    const runButton = page.getByRole('button', { name: /重新智能匹配|匹配执行中/ })
    await expect(runButton).toBeVisible()

    if (data.readiness.blocker) {
      // CI 的全新种子库没有填 API Key，会命中模型配置阻断；
      // 本地联调栈若已配 Key，则走下面的可运行分支。
      await expect(page.getByText('发起匹配前要先满足这几项')).toBeVisible()
      await expect(
        page.getByText(data.readiness.blocker.label, { exact: true })
      ).toBeVisible()
      await expect(
        page.getByText(data.readiness.blocker.message, { exact: true })
      ).toBeVisible()
      await expect(runButton).toBeDisabled()
    } else {
      expect(data.readiness.can_run).toBe(true)
      expect(data.readiness.checks.map((item) => item.key)).toEqual(
        expect.arrayContaining(['profile', 'intro', 'preference', 'moment'])
      )

      // 租期匹配候选是 readiness 的硬前置检查之一，可运行时应当出现在检查清单里。
      const leaseCheck = data.readiness.checks.find((item) => item.key === 'lease_pool')
      expect(leaseCheck, 'member01 有计划租期，可运行时应有 lease_pool 检查').toBeTruthy()
      expect(leaseCheck.ok).toBe(true)

      if (data.task) {
        await expect(page.getByText('这一次的匹配任务', { exact: true })).toBeVisible()
        await expect(page.getByText('调度过程', { exact: true })).toBeVisible()
      } else {
        await expect(page.getByText('还没有发起过匹配', { exact: true })).toBeVisible()
      }
    }

    // 只读约束：无论如何都不允许点「重新智能匹配」或发出 /match/rerun。
    expect(rerunCalls, 'E2E 不允许触发 /api/match/rerun').toBe(0)
    await expectNoPlaceholderLeak(page)
  })

  test('无模型 Key 时 readiness 阻断并禁用发起按钮（接口桩）', async ({ page }) => {
    const checks = [
      readinessCheck('profile', '租客档案', true, '昵称「小宋」'),
      readinessCheck('intro', '自我介绍', true, '142 个字'),
      readinessCheck('preference', '合住偏好', true, '必须 3 项、可放宽 2 项'),
      readinessCheck('moment', '租客动态', true, '4 条'),
      readinessCheck(
        'model',
        '调度模型',
        false,
        '「调度决策模型」还没有填写 API Key，请联系管理员到【AI模型配置】补上'
      )
    ]
    const data = matchPageData({
      readiness: { checks, blocker: checks[checks.length - 1], can_run: false }
    })

    await stubMatchApi(page, data)
    await seedSession(page, STUB_MEMBER)
    await page.goto('/front/myMatch')

    await expect(page.getByText('发起匹配前要先满足这几项')).toBeVisible()
    await expect(page.locator('.check-row')).toHaveCount(checks.length)
    await expect(page.getByText('调度模型', { exact: true })).toBeVisible()
    await expect(page.getByText(/还没有填写 API Key/)).toBeVisible()
    await expect(page.getByText(/AI模型配置/)).toBeVisible()
    await expect(page.getByRole('button', { name: '重新智能匹配' })).toBeDisabled()
    await expectNoPlaceholderLeak(page)
  })

  test('租期匹配候选不足时展示租期 blocker 文案（接口桩）', async ({ page }) => {
    const leaseBlocker = readinessCheck(
      'lease_pool',
      '租期匹配候选',
      false,
      '当前候选池里没有计划租期与您相差 2 档以内的租客（您的计划租期：3个月以下）。' +
        '短期过渡可以理解，但硬规则不允许跨档合租；请调整计划租期，或等新的短租租客再发起。',
      '/front/memberProfile',
      '去调整计划租期'
    )
    const checks = [
      readinessCheck('profile', '租客档案', true, '昵称「小宋」'),
      leaseBlocker
    ]
    const data = matchPageData({
      readiness: { checks, blocker: leaseBlocker, can_run: false }
    })

    await stubMatchApi(page, data)
    await seedSession(page, STUB_MEMBER)
    await page.goto('/front/myMatch')

    await expect(page.getByText('发起匹配前要先满足这几项')).toBeVisible()
    await expect(page.getByText('租期匹配候选', { exact: true })).toBeVisible()
    await expect(page.getByText(/相差 2 档以内/)).toBeVisible()
    await expect(page.getByRole('button', { name: '去调整计划租期' })).toBeVisible()
    await expect(page.getByRole('button', { name: '重新智能匹配' })).toBeDisabled()
    await expectNoPlaceholderLeak(page)
  })

  test('未填写档案时提示先补档案（接口桩）', async ({ page }) => {
    const profileBlocker = readinessCheck(
      'profile',
      '租客档案',
      false,
      '还没有填写租客档案，请先到【租客档案】把档案填好',
      '/front/memberProfile',
      '去填写租客档案'
    )
    const data = matchPageData({
      has_profile: false,
      readiness: { checks: [profileBlocker], blocker: profileBlocker, can_run: false }
    })

    await stubMatchApi(page, data)
    await seedSession(page, STUB_MEMBER)
    await page.goto('/front/myMatch')

    await expect(page.getByText('先补租客档案', { exact: true })).toBeVisible()
    await expect(page.getByText('还没有填写租客档案', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '去填写租客档案' })).toBeVisible()
    await expect(page.getByRole('button', { name: '重新智能匹配' })).toBeDisabled()
    await expectNoPlaceholderLeak(page)
  })

  // 回归用例：MyMatch.vue 的 load() 必须兜住 500 的 reject，
  // 页面给错误提示，但不能出现未处理的 Promise rejection（pageerror）。
  test('匹配接口 500 时给出错误提示且无 pageerror', async ({ page }) => {
    await stubMatchApi(page, null, { status: 500 })
    await seedSession(page, STUB_MEMBER)

    const responsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/match/my')
    )
    await page.goto('/front/myMatch')
    await responsePromise

    await expect(page.getByRole('heading', { name: '智能匹配' })).toBeVisible()
    await expect(page.getByText(/服务器处理出错/)).toBeVisible()
    await expectNoPlaceholderLeak(page)
  })
})
