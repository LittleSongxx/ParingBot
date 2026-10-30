# ParingBot 前端视觉规范（NewsClaw 风格浅色工作台）

> 目标：把 31 个页面统一到「浅灰背景 + 白色卡片 + 蓝色强调 + 柔和圆角/阴影」的视觉体系；
> 只改样式与展示结构，不改接口、路由与业务逻辑。

## 1. 设计 token（`frontend/src/assets/css/global.css` 的 `:root`）

| 语义 | 变量 | 值 |
|---|---|---|
| 页面背景 | `--pb-bg-grad` | `linear-gradient(180deg,#f7f8fa,#eef1f6 52%,#e8edf6)` |
| 卡片/表面 | `--pb-surface` | `#ffffff` |
| 次级表面 | `--pb-surface-2` / `--pb-surface-3` | `#f8fafc` / `#f1f5f9` |
| 边框 | `--pb-line` / `--pb-line-strong` | `rgba(17,24,39,.09)` / `.16` |
| 主文字 | `--pb-text` | `rgba(17,24,39,.94)` |
| 次文字 | `--pb-muted` | `rgba(17,24,39,.56)` |
| 弱文字 | `--pb-faint` | `rgba(17,24,39,.38)` |
| 品牌蓝 | `--pb-brand` / `--pb-brand-dark` | `#2563eb` / `#1d4ed8` |
| 品牌浅底 | `--pb-brand-soft` | `rgba(37,99,235,.09)` |
| 成功/警告/危险/紫/青 | `--pb-ok` `--pb-warn` `--pb-danger` `--pb-violet` `--pb-cyan` | `#10b981 #f59e0b #ef4444 #8b5cf6 #06b6d4` |
| 对应浅底 | `--pb-ok-soft` `--pb-warn-soft` `--pb-danger-soft` `--pb-violet-soft` `--pb-cyan-soft` | 见 global.css |
| 圆角 | `--pb-radius` / `--pb-radius-sm` / `--pb-radius-lg` | `14px` / `10px` / `20px` |
| 卡片阴影 | `--pb-shadow-card` / hover | 见 global.css |
| 字体 | `--pb-font` | Noto Sans SC / PingFang SC / Microsoft YaHei |
| 等宽 | `--pb-mono` | JetBrains Mono / SFMono / Consolas |

## 2. 可直接使用的全局类

- 容器：`.card`、`.block-card`、`.panel`、`.soft-panel`、`.empty-card`、`.summary-box`
- 标题：`.page-head`（`h2` + `.page-tip` + `.page-head-action`）、`.block-title`、`.section-title`
- 指标：`.metric-grid`、`.metric-tile`、`.metric-label`、`.metric-value`
- 标签/状态：`.chip` + `.chip-blue/green/amber/red/violet/cyan`、`.status-dot`、`.count-chip`
- 表单说明：`.table-tip`、`.form-tip`、`.check-row`、`.code-line`
- 动画：页面进入自动 `pb-fade-up`；卡片 hover 有轻微抬升

## 3. 旧颜色迁移表

| 旧值 | 新用法 |
|---|---|
| `#1F6F6B` `#24625E` `#2A7F7A` `#4F8F8A` `#84B5B2` `#A9CFCB` `#C4DCDA` | `var(--pb-brand)` / `var(--pb-brand-dark)` / `var(--pb-brand-soft)` |
| `#DFECEB` `#EFF6F5` `#F5FAF9` `#F2F8F7` `#E4F0EF` `#CDE3E1` `#D5E8E6` | `var(--pb-brand-soft)` / `var(--pb-surface-2)` |
| `#0066bc` | `var(--pb-brand)` |
| `#67c23a` / `#e6a23c` / `#f56c6c` | `var(--pb-ok)` / `var(--pb-warn)` / `var(--pb-danger)`（配对应 `-soft` 底） |
| `#303133` `#333` | `var(--pb-text)` |
| `#606266` `#666` | `rgba(17,24,39,.78)` |
| `#909399` `#999` `#888` `#bbb` | `var(--pb-muted)` / `var(--pb-faint)` |
| `#fafafa` `#f7f7f7` `#f8f8ff` | `var(--pb-surface-2)` |
| `#eee` `#e4e7ed` `#dcdfe6` | `var(--pb-line)` |

## 4. 页面改造约定

1. 页面根节点保留原 class（如 `.main-content`），内部再套 `.page-wrap` 或直接卡片；不要改路由与数据字段。
2. 页头统一 `.page-head`（`.with-action` 表示右侧有主按钮）；标题 22px/650，说明文字 13px `--pb-muted`。
3. 内容块统一 `.card` / `.block-card`，不要再用 5px 圆角 + 重投影；同一页卡片间距 14-16px。
4. 状态不要用纯文字色，改用 `.chip-*` 或 Element `el-tag`（全局已改成药丸形）。
5. 表格沿用全局样式：去掉页面内自定义表头背景、粗边框；筛选条放进一个 `.card` 或 `.soft-panel`。
6. 弹窗内容用 `.soft-panel` / `.block-card` 分组，不要密集平铺。
7. 强调数字（轮次、候选数、通过数、耗时）用 `.metric-tile` 或大号加粗数字。
8. 时间线/漏斗：主色蓝渐变（`linear-gradient(90deg,#60a5fa,#2563eb)`），轨道 `--pb-surface-3`。
9. 图标：使用 Element Plus 图标，放在 32-36px 的浅色圆角方块里（`background: var(--pb-brand-soft); color: var(--pb-brand)`），不要裸大图标。
10. 响应式：>=1200 三列/两列，960-1200 两列，<768 单列；表格窄屏可横向滚动。
