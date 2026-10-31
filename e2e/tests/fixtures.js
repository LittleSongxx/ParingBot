import { test as base, expect } from '@playwright/test'

/**
 * 所有页面用例共用的 pageerror 守卫。
 *
 * 业务代码没有全局 errorHandler，未捕获的 JS 异常只会出现在浏览器
 * pageerror 事件里；页面还能显示，但功能已经坏了，CI 必须失败。
 */
export const test = base.extend({
  page: async ({ page }, use) => {
    const pageErrors = []
    page.on('pageerror', (error) => pageErrors.push(error))

    await use(page)

    const detail = pageErrors.map((error) => error.stack || error.message).join('\n---\n')
    expect(pageErrors, `页面出现未捕获异常（pageerror）：\n${detail}`).toEqual([])
  }
})

export { expect }
