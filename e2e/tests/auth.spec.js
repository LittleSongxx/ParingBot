import { test, expect } from './fixtures.js'
import {
  ADMIN,
  MEMBER,
  expectNoPlaceholderLeak,
  loginViaApi,
  seedSession
} from './helpers.js'

test.describe('登录页与路由守卫', () => {
  test('演示账号 chip 填入账号密码，并登录到管理端首页', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()

    // 管理员 chip 把账号和密码一起填进表单
    await page.getByRole('button', { name: /管理员 admin \/ admin123/ }).click()
    await expect(page.getByPlaceholder('请输入账号')).toHaveValue(ADMIN.username)
    await expect(page.getByPlaceholder('请输入密码')).toHaveValue(ADMIN.password)

    await page.getByRole('button', { name: /登\s*录/ }).click()
    await expect(page).toHaveURL(/\/manager\/home$/)
    await expect(page.getByRole('heading', { name: '系统首页' })).toBeVisible()

    const stored = await page.evaluate(() =>
      JSON.parse(localStorage.getItem('xm-user') || '{}')
    )
    expect(stored.role).toBe('ADMIN')
    expect(stored.token).toBeTruthy()
    await expectNoPlaceholderLeak(page)
  })

  test('错误密码提示统一文案，且不会写入登录态', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('请输入账号').fill(MEMBER.username)
    await page.getByPlaceholder('请输入密码').fill('e2e-wrong-password')
    await page.getByRole('button', { name: /登\s*录/ }).click()

    await expect(page.getByText('账号或密码错误', { exact: true })).toBeVisible()
    await expect(page).toHaveURL(/\/login$/)
    expect(await page.evaluate(() => localStorage.getItem('xm-user'))).toBeNull()
  })

  test('未登录访问租客端和管理端都被路由守卫送到登录页', async ({ page }) => {
    await page.goto('/front/home')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()

    await page.goto('/manager/home')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  })

  test('租客账号访问管理端会被送回租客端', async ({ page, request }) => {
    const member = await loginViaApi(request, MEMBER)
    await seedSession(page, member)

    await page.goto('/manager/home')
    await expect(page).toHaveURL(/\/front\/home$/)
    await expect(page.getByRole('heading', { name: /把找室友/ })).toBeVisible()

    // 管理端具体页面同样按角色拦截
    await page.goto('/manager/user')
    await expect(page).toHaveURL(/\/front\/home$/)
    await expectNoPlaceholderLeak(page)
  })
})
