/**
 * 在跑页面用例之前先确认「栈真的可用」。
 *
 * CI 里 docker compose 已经启动，但服务 healthy 到种子数据可登录之间
 * 仍可能有几秒空窗；本地也可能忘了启动栈。这里用一次只读登录探测，
 * 避免每条用例各自超时后只看到一句 element not found。
 */
const WAIT_MS = 120_000
const INTERVAL_MS = 2_000

async function probe(baseURL, username, password) {
  const response = await fetch(`${baseURL}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  })
  const body = await response.json().catch(() => ({}))
  return {
    ok: response.ok && body.code === '200',
    detail: `HTTP ${response.status} ${JSON.stringify(body).slice(0, 200)}`
  }
}

export default async function globalSetup(config) {
  const baseURL = (
    config.projects?.[0]?.use?.baseURL ||
    process.env.E2E_BASE_URL ||
    'http://127.0.0.1:8080'
  ).replace(/\/+$/, '')
  const username = process.env.E2E_ADMIN_USERNAME || 'admin'
  const password = process.env.E2E_ADMIN_PASSWORD || 'admin123'
  const deadline = Date.now() + WAIT_MS
  let lastDetail = 'not probed yet'

  while (Date.now() < deadline) {
    try {
      const result = await probe(baseURL, username, password)
      if (result.ok) {
        console.log(`[e2e] stack ready at ${baseURL}`)
        return
      }
      lastDetail = result.detail
    } catch (error) {
      lastDetail = error.message
    }
    await new Promise((resolve) => setTimeout(resolve, INTERVAL_MS))
  }

  throw new Error(
    `[e2e] 栈在 ${WAIT_MS / 1000}s 内没有就绪：${baseURL}\n` +
      `最后一次探测：${lastDetail}\n` +
      '请确认 docker compose 已启动，且 admin/admin123 演示账号可登录。'
  )
}
