# ParingBot 前端 E2E 冒烟测试

基于 Node `@playwright/test` 的只读冒烟套件。目标是守住「登录 / 路由守卫 /
租客端 / 管理端 / readiness 阻断 / 错误状态 / 404」这些上线前必须成立的页面行为。

## 覆盖范围

| 文件 | 覆盖内容 |
| --- | --- |
| `tests/auth.spec.js` | 演示账号 chip 填入、管理员登录到 `/manager/home`、错误密码提示、未登录访问 `/front/home` 与 `/manager/home` 跳登录、租客访问管理端被送回租客端 |
| `tests/tenant.spec.js` | `/front/home`、`/front/memberProfile`、`/front/myPreference`、`/front/myMatch` 真实 readiness；无模型 Key、租期候选不足、未填档案、接口 500 的页面状态（接口桩） |
| `tests/manager.spec.js` | `/manager/home`、`/manager/matchTrace`（含只读运行详情）、`/manager/user` 列表与姓名筛选、`/manager/sysConfig` |
| `tests/not-found.spec.js` | 未知路由 → `/404` → 回到首页落到 `/login` |
| `tests/api-contract.spec.js` | readiness 字段契约、租期候选检查、无 Key 种子栈的模型阻断、管理端列表不返回密码、未登录 401 |
| `tests/fixtures.js` | 每条页面用例收集并断言 `pageerror` 为空 |
| `tests/helpers.js` | API 登录、localStorage 注入、`undefined`/`NaN` 泄漏断言、`/match/my` 接口桩 |

## 只读约束

- 不调用 `POST /api/match/rerun`，不创建、修改、删除任何业务数据。
- 不使用 `member02`（本地联调时它可能正在跑真实匹配）。
- 不调用真实模型；readiness 阻断与错误状态通过拦截 `/api/match/my` 的接口桩覆盖。
- 会写一条登录失败记录（错误密码用例），这是登录限流计数，不写业务表。

## 本地运行

```bash
cd e2e
npm ci
npx playwright install chromium   # 首次
npm test
```

默认打 `http://127.0.0.1:8080`。可用环境变量覆盖：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `E2E_BASE_URL` | `http://127.0.0.1:8080` | 被测栈地址 |
| `E2E_ADMIN_USERNAME` / `E2E_ADMIN_PASSWORD` | `admin` / `admin123` | 管理员演示账号 |
| `E2E_MEMBER_USERNAME` / `E2E_MEMBER_PASSWORD` | `member01` / `123456` | 租客演示账号 |
| `E2E_BROWSER_CHANNEL` | 空 | 本地不下载 Chromium 时可设为 `chrome` 使用系统 Chrome |
| `CI` | 空 | 设置后失败重试 1 次 |

## 产物

- `playwright-report/`：HTML 报告
- `test-results/`：失败截图、视频、trace、JUnit XML

两者已加入 `.gitignore`，CI 在失败时作为 artifact 上传。
