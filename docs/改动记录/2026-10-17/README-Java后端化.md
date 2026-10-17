# README Java 后端化与新截图

## 需求

把仓库首页从“商城 + 导购 Agent”的混合叙事改成 Java 交易后端的单一叙事：9 个 Spring Boot 服务、每服务独立 schema、本地事务 + Outbox + 幂等 + 补偿 + 对账。保留原 README 的排版语言（logo、徽章、HTML 截图、表格、章节），但不出现 AI/导购/知识库/ReAct/Qdrant 内容；架构图与截图都重新制作。

## 变更

- `README.md` 全量重写：首屏定位、演示账号、订单全链、8 张截图、后台、Java-only 架构、三条主链、技术栈、目录、快速开始、验证、指标、运维、10 条关键决策、已知边界。
- 新增 `docs/assets/backend-architecture.svg` 与 `backend-architecture.png`（2360×1320）：左侧 9 个 Java 服务（默认端口 18080–18088），右侧数据面/读模型/一致性面板，去掉 Python 导购块。
- 用本地栈重新截 8 张 1440×900 截图：`home`、`product-detail`、`cart`、`checkout`、`orders`、`admin-dashboard`、`admin-order`、`admin-refund-review`。截图前用浏览器脚本隐藏 AI 入口与工具栏；管理端 gallery 只读横幅与退出登录保留。
- 旧 AI 截图 `assistant.png`、`product-guide.png`、`admin-knowledge.png` 移到 `docs/assets/assistant/`，不删除历史资产；根 README 不再引用。
- 退款复核截图使用预置的 `MANUAL_REVIEW` 退款单；gallery 只读，动作列按真实权限为空，不做假的“审批成功”画面。

## 关键源码/资产

- `README.md`
- `docs/assets/backend-architecture.svg`、`docs/assets/backend-architecture.png`
- `docs/assets/screenshots/*.png`
- `docs/assets/assistant/*.png`（归档）

## 验证

- 本地后端 9 服务与前端全部健康后截图；截图尺寸 1440×900，逐张检查无 AI 入口、无遮挡、无错误状态。
- `grep` 根 README，无 `assistant`/`AI`/`ReAct`/`Qdrant`/`导购`/`知识库` 文案与图片引用。
- README 中所有图片路径存在；`./scripts/dev.sh apps-check` 通过（9 个 Nacos 注册）。

原始截图位于 `docs/assets/screenshots/`；本文件不复制图片。

## 未完成/边界

- 线上 `smartlect.cn` 仍是上一版页面与截图来源；本次只更新仓库 README 与本地截图，没有部署新的文档/前端。
- gallery 账号的写操作仍由服务端拒绝；截图只展示读能力与退款复核队列。

## 关联版本

工作区基于 `cc73bba`，本次改动未提交。
