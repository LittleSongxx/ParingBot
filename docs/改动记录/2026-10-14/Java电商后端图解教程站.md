# Java 电商后端图解教程站（JavaGuide 式）

## 需求

用户要求把项目 **Java 电商后端部分**（不含 AI Agent）做成图文并茂的讲解：

- 图片详细、文字只写最关键点、多分点、可读性优先；
- 形态对标 JavaGuide：左侧章节导航栏 + 右侧本页目录栏，点击跳转；
- 用一个具体例子贯穿全链路辅助理解。

计划由 4 个并行 Explore 子代理分域调研事实（网关/认证、订单/支付、购物车/券/部署、商品/搜索/库存），每个论断要求带 `path:line`；关键绝对词论断（全库无 `@FeignClient`、无 Seata 依赖、订单 9 状态枚举）由主会话亲自 grep 复核后采信。实现为纯静态站点，无新增运行时依赖。

## 交付物

`教程/Java电商后端图解/`（全部新增文件，未改任何 Java/配置代码）：

| 文件 | 内容 |
| --- | --- |
| `index.html` | 首页：技术栈徽章、贯穿案例卡片、13 章卡片网格、阅读路径 |
| `assets/site.css` | JavaGuide 式三栏布局、明暗双主题、SVG 角色色板（8 类角色 × 2 主题） |
| `assets/site.js` | 左导航（分组折叠持久化）、右目录自动生成 + IntersectionObserver 滚动高亮、上下页、阅读进度条、暗色切换、证据锚点自动链接 GitHub 对应行（锚定 commit 0e94e7c） |
| `pages/01-start.html` | 项目速览：根约束（ADR-0006 弃 Seata → 一切写操作自带幂等+补偿）、10 模块表、刻意不做清单、贯穿案例故事线图 |
| `pages/02-architecture.html` | 全景架构图（4 层 + 中间件 + Canal 链路）、Dubbo 调用关系图（star 拓扑，标注 FeignSupport 命名是历史遗留） |
| `pages/03-gateway.html` | 网关四道关卡图（InternalToken −200 / Auth −100 剥头+两层校验 / Sentinel 限流 / 服务层注解）、登录 8 步时序图、三演示账号权限矩阵 |
| `pages/04-product.html` | 商品数据模型图（属性宽表 + SKU hash + 跨库 stock）、搜索双分支图（ES wildcard 出 ID / LIKE 回退）、Canal→MQ→ES 同步图、详情多级缓存图（布隆→L1/L2→实时库存） |
| `pages/05-cart.html` | 加购/结算图（纯 MySQL、价格双轨、增量 UPDATE） |
| `pages/06-stock.html` | 库存扣减图（INSERT IGNORE 抢幂等键 → TreeMap 排序 → 条件 UPDATE → affected 分流；回补 = 删键 + SHA-256 去重） |
| `pages/07-order.html` | **核心**：下单五阶段大图（幂等账本→只读准备→锁远程→短本地事务→事务外远程写→反向补偿）+ 右侧贯穿案例账本；幂等重放矩阵表 |
| `pages/08-pay.html` | 支付成功事件流时序（mock complete→条件更新→同事务 Outbox→消费三层幂等→CAS 推进→paid_amount 分摊）、Outbox 生命周期状态图（PENDING/SENDING/SENT/FAILED/EXHAUSTED + 5s 扫描） |
| `pages/09-lifecycle.html` | 9 状态状态机全图（10 事件全部合法迁移）、CAS 实现、主路径+保险丝时间轴（15min/1h/7d/600s） |
| `pages/10-coupon-rush.html` | 抢券全链路图（双层限流→Lua 三键预占→DB 条件扣→0.01 元单→四形态超时→10min 对账）、券状态流转图（NOUSE/CANT/USED + 秒杀反向激活） |
| `pages/11-refund.html` | 退款 Saga 图（PENDING_PAYMENT→PAYMENT_CONFIRMED→STOCK_PENDING→COMPLETED，pay/order/stock 三段职责） |
| `pages/12-consistency.html` | 一致性总纲：五层防线图 + 场景×防线对照表 + 「为什么敢移除 Seata」 |
| `pages/13-deploy.html` | ECS 三节点拓扑图、版本编排速查表、两条踩坑记录（ES 内网绑定 / nacos-client 版本对齐） |

贯穿案例（全部来自真实种子数据 `backend/data/02_catalog_seed.sql`）：买家 `shopper@smartlect.demo`（userId 8800000002）购买 iPhone 17 Pro Max 银色 256G（productId 895150981058759，hash 137e14ea…，¥8999×564 件），用券 CPDEMOBUYER01（无门槛 ¥5），应付 8994；每章末尾「案例进度」框接力。

## 讲解口径（explain 技能约束）

- 每章先给「这张图看不到的事」或反直觉点：如 ES 索引装了 IK 但谓词是 wildcard（与 LIKE 逐字等价是设计目标）、网关故意不下发身份头、postOrder 故意不标 @Transactional（18.1s 占连接事故）、抢券编排在 order 不在 coupon。
- 文字全部为要点列表，机制写进 SVG 节点；证据锚点 `a.ev[data-p][data-l]` 由 site.js 统一链接到 GitHub blob@0e94e7c 对应行，悬停显示完整路径。

## 验证方式与证据（渲染验收）

- 工具：本机 playwright 1.63.0（chromium-1243，`--browser=chromium --full-page`）截 1440×900 全页图，视觉模型复查布局/文字溢出/乱码。
- 初轮发现 5 处真实渲染缺陷并已修复：ch10 紫色「Outbox 定时消息」竖线穿越右侧两张卡片（改走两栏走廊 x=490 + 竖排标签）、ch10 券状态图 validateAndLock 标签压节点（拆两行）、ch09 COUPON_RUSH_PAY_SUCCESS 标签超画布右缘（上移）、ch08 事件流标签④超宽（缩短）、ch11 退款单号行溢出色块（扩块拆行）、ch13 DLedger 行压边（缩短）。
- 复测截图（修复后）通过：三栏布局正常、当前章高亮正确、SVG 无文字重叠/截断、无乱码。首页/02/07 为修复前轮次但问题仅存在于上述章节，页面本身复查通过。
- 终验：全部 14 个页面均完成全页截图（结构完整、体积正常）；Playwright 收集控制台/页面错误 = 0；每页侧栏 14 项、本页目录与上下页均正确生成（首页无上一页属预期）。
- 截图与指纹：`eval/verification/2026-10-14/sl-*.png`（index 85b01e33bfff16b6、02-architecture 968ad33f128906e9、07-order e58a58db69cc0d2e、09-lifecycle-v2 5a1c799de0c210f9、10-coupon-rush-v2 9a8acadc274ab30b、11-refund-v2 c1e34076b5520420）。
- 打开方式：浏览器直接打开 `教程/Java电商后端图解/index.html`（纯静态、离线可用、支持 file://）。

## 内容事实核对说明

- 内容性论断全部来自子代理调研返回的 `path:line`，其中三处绝对词论断由主会话 grep 复核：`@FeignClient` 全库 0 处、seata 依赖与 `@GlobalTransactional` 全库 0 处、`OrderStatusEnum` 9 个状态值与迁移表一致。
- 已知表述取舍：案例中 payOrderId/orderId 用「PO-DEMO」示意值（真实格式未在调研中取证），教程中标注为示意；其余数字（价格、库存、端口、表名、键名、超时时长、重试参数）均来自代码/种子数据原文。

## 未完成项

- 未做移动端真机截图验证（CSS 已写 <960px 折叠侧栏逻辑，桌面端验证通过）。
- 站点为纯静态，无搜索框、无构建流程；如需发布到 GitHub Pages 需另行配置。

## 关联代码版本

- 基线 commit：0e94e7c（证据锚点与调研均在此版本上进行）。
- 回滚说明：删除 `教程/Java电商后端图解/` 与 `eval/verification/2026-10-14/sl-*.png` 即完全回滚，无代码/配置影响。
