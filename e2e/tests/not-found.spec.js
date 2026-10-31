import { test, expect } from './fixtures.js'
import { expectNoPlaceholderLeak } from './helpers.js'

test('未知路由渲染 404 页面，回到首页会落到登录页', async ({ page }) => {
  await page.goto('/e2e-route-that-does-not-exist-20261031')

  await expect(page).toHaveURL(/\/404$/)
  await expect(page.getByRole('heading', { name: '404', exact: true })).toBeVisible()
  await expect(
    page.getByText('这个页面不存在，可能已经被移动或删除了。', { exact: true })
  ).toBeVisible()

  await page.getByRole('button', { name: '回到首页' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await expectNoPlaceholderLeak(page)
})
