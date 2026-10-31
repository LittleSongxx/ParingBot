import { defineConfig, devices } from '@playwright/test'

// 被测栈默认是 Docker Compose 暴露的 http://127.0.0.1:8080。
// CI 与本地都可以用 E2E_BASE_URL 覆盖；本地如果没有 Playwright 下载的
// Chromium，可设置 E2E_BROWSER_CHANNEL=chrome 直接用系统 Chrome 跑。
const baseURL = (process.env.E2E_BASE_URL || 'http://127.0.0.1:8080').replace(/\/+$/, '')
const browserChannel = process.env.E2E_BROWSER_CHANNEL

export default defineConfig({
  testDir: './tests',
  globalSetup: './global-setup.js',

  // 所有用例都打同一套 Docker 栈和同一批演示数据：
  // 串行执行，避免登录限流、分页和实时匹配进度互相干扰。
  fullyParallel: false,
  workers: 1,

  // 页面里有真实接口和实时匹配轮询，单条用例给足等待时间。
  timeout: 45_000,
  expect: { timeout: 10_000 },

  // CI 失败自动重跑一次，本地保持一次就跑完，便于复现。
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,

  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
    ['junit', { outputFile: 'test-results/junit.xml' }]
  ],

  use: {
    baseURL,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    // 失败时保留现场：截图、视频、trace 都上传到 CI artifact
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
    ...(browserChannel ? { channel: browserChannel } : {})
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ],

  outputDir: 'test-results'
})
