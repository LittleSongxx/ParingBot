# F4 真实管理浏览器检查

由根执行者安排在 Maven、MySQL 与投放驱动器结束之后串行运行。只连接本项目 `web-admin`；不要复用旧项目浏览器服务，不把本目录模拟 HTTP 单测当作本检查结果。

工具预检：`npx` 和 Playwright CLI 可用；skill 包装脚本在当前环境需使用 `bash /home/song/.codex/skills/playwright/scripts/playwright_cli.sh`。默认 Chrome 路径不存在，可用本机已安装 Chromium，在 Git 忽略的 `run/` 写单独 CLI 配置，指定 `browserName=chromium`、`isolated=true`、loopback 页面及已存在的 `executablePath`。每轮使用自己的命名会话，禁止 `close-all` / `kill-all`。

1. 根启动器确认 `web-admin` 健康后，打开 `/admin/`，先取无密码的 accessibility snapshot。注册页面 JS 异常与广告写请求计数；不要记录登录请求正文或 cookie。
2. 通过 UI 的“刷新验证码”按钮请求本次 Java challenge。只在本项目 Redis 读取该 challenge 值；账号/密码仅在本地子进程内读取 `run/runtime.env`。使用 mode-600 临时文件传给 CLI `run-code --filename`，全程捕获输出并只保留脱敏结果；不得将密码作为 shell 参数或打印代码回显。登录后清空任何密码输入，再截图并删除临时文件。不保存可复用的浏览器 cookie 文件。
3. GET 当前投放快照，选择一个商品/SKU 真实可售的资源（管理端商品页可核对；原 f 系列校验脚本已退役）。建立独立名字的活动和素材 DRAFT：新活动预算先为 0，原活动/账本保留。截图和回执必须明确 DRAFT，没有隐式授权或启用。
4. 在页面填写明确授权范围、累计上限、变动上限和有效期。若已有账户，填当前稳定 grant 作为替代关系；展开核对首次计划的活动/素材版本和正文，勾选明确批准后保存。核对响应 `expected_campaign_versions` / `expected_creative_versions` 对应的 `plan_snapshot` 与 hash，累计 `spent_cents` 不变。
5. 用 UI 动作确认面板设置新活动预算，然后依次启用活动、启用素材。分别暂停/恢复素材、暂停/恢复活动；每次通过网络回执和最新 GET 快照检查资源 ID、版本、before/after、授权 hash、状态与新库存观测。
6. 验证并发版本冲突：第一页准备一个暂停动作并保留原版本；第二个同源页面通过 UI 完成同一资源的一次暂停。第一页确认旧版本，核对 409 原因可见、只读刷新显示 PAUSED，原动作只提交一次。关闭旧动作面板，使用新版本显式恢复。禁止改测试为通用 PATCH status。
7. 记录广告写请求数量后刷新页面，重新 GET 的累计预算/花费、授权与动作 ID 不变，写请求数量不增加。预算/草稿/审批不能因页面刷新重放。
8. 在 1365px 和 390px 视口分别截图到 `output/playwright/`，检查 `document.documentElement.scrollWidth <= innerWidth`、交互按钮可见、无 JS 异常。把预期的匿名 401、故意制造的 409 HTTP 控制台记录和非预期错误分别报告，不删除失败证据。

证据报告只保存本项目 URL、时间、资源/动作/授权 ID、整数分金额、版本/hash、状态、截图相对路径、请求计数和异常摘要；不得保存 password、cookie、CSRF 或任何 key。失败后写清实际失败位置，保留服务器已完成的动作，不用 reset-demo 隐藏问题。
