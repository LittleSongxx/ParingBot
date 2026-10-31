import { test, expect } from './fixtures.js'
import { ADMIN, expectNoPlaceholderLeak, openAs } from './helpers.js'

test.describe('管理端页面（admin，只读）', () => {
  test('系统首页加载快捷入口与当前管理员', async ({ page, request }) => {
    await openAs(page, request, '/manager/home', ADMIN)

    await expect(page).toHaveURL(/\/manager\/home$/)
    await expect(page.getByRole('heading', { name: '系统首页' })).toBeVisible()
    await expect(page.getByText('快捷入口', { exact: true })).toBeVisible()
    await expect(page.locator('.manager-topbar .user-name')).toHaveText('平台管理员')
    await expect(page.getByText('调度时间线', { exact: true }).first()).toBeVisible()
    await expectNoPlaceholderLeak(page)
  })

  test('调度时间线列出运行记录，并只读查看运行详情', async ({ page, request }) => {
    await openAs(page, request, '/manager/matchTrace', ADMIN)

    await expect(page.getByRole('heading', { name: '调度时间线' })).toBeVisible()
    const rows = page.locator('.el-table__row')
    await expect(rows.first()).toBeVisible()
    await expect(rows.first()).toContainText(/MATCH-\d{14}-[0-9a-f]{6}/)

    // 「查看过程」只发 GET /trace/detail，不改任何数据
    await rows.first().getByRole('button', { name: '查看过程' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByText('运行概览', { exact: true })).toBeVisible()
    await expect(page.getByText('候选漏斗', { exact: true })).toBeVisible()
    await expectNoPlaceholderLeak(page)
  })

  test('用户管理列表加载并可按姓名筛选', async ({ page, request }) => {
    await openAs(page, request, '/manager/user', ADMIN)

    await expect(page.getByRole('heading', { name: '用户管理' })).toBeVisible()
    const rows = page.locator('.el-table__row')
    await expect(rows.first()).toBeVisible()
    await expect(rows).toHaveCount(10)
    await expect(page.locator('.el-table__header')).toContainText('账号')
    await expect(page.locator('.el-table__header')).toContainText('角色')

    const filtered = page.waitForResponse((response) => {
      if (!response.url().includes('/api/user/selectPage')) return false
      return new URL(response.url()).searchParams.get('name') === '平台管理员'
    })
    await page.getByPlaceholder('请输入姓名查询').fill('平台管理员')
    await page.getByRole('button', { name: '查询' }).click()
    await filtered

    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText('admin')
    await expect(rows.first()).toContainText('平台管理员')
    await expect(rows.first()).toContainText('管理员')
    await expect(page.locator('.el-pagination__total')).toContainText('共 1 条')
    await expectNoPlaceholderLeak(page)
  })

  test('系统参数展示 7 条运行时参数', async ({ page, request }) => {
    await openAs(page, request, '/manager/sysConfig', ADMIN)

    await expect(page.getByRole('heading', { name: '系统参数' })).toBeVisible()
    await expect(page.getByText('SUPERVISOR_MAX_ROUND', { exact: true })).toBeVisible()
    await expect(page.getByText('主管调度轮数上限', { exact: true })).toBeVisible()
    await expect(page.locator('.el-table__row')).toHaveCount(7)
    await expectNoPlaceholderLeak(page)
  })
})

