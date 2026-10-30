# 真实模型评测 Runbook

> 目标：用**真实模型**跑通 ParingBot 的多 Agent 匹配链路，得到可横向比较的评测记录。
> 与离线 Phase 0 评测的分工：
> - `eval/run_eval.py`：不需要 Key，校验「资料教练 / 匹配解读官」的输出规则；
> - 本 Runbook：需要 Key，跑当前**已实现**的四 Agent 匹配链路，记录过程与结果。
>
> 目前两个助手功能还没开发，所以真实模型评测的落点是「现有匹配链路」；等 Phase 1 功能上线后，
> 用 `eval/run_eval.py --outputs` 接它们的真实输出，再按同一套规则和人工 rubric 评测。

## 0. 一句话准备

```bash
cp .env.eval.example .env.eval        # 已在仓库里；文件默认存在但 Key 为空
# 编辑 .env.eval：填 EVAL_API_KEY；EVAL_PROVIDER 默认 deepseek
python eval/configure_models.py       # 写四用途模型配置 + 连一次真实模型
python eval/run_live_eval.py          # 跑一次真实匹配，输出报告
```

## 1. 前提

- Docker 栈已经启动：`docker compose ps` 三个服务 healthy，应用 <http://127.0.0.1:8080>；
- 管理员账号可登录（默认 `admin/admin123`）；
- 评测租客账号可登录（默认 `member02/123456`，已有完整档案/偏好/动态）；
- 有至少一个供应商的 API Key。

> 运行时的 `.env` 只放数据库/JWT/端口等部署配置；模型 Key 不在 `.env` 里，
> 而是在数据库 `ai_model_config` 表（管理端【AI模型配置】页）。
> `.env.eval` 是评测脚本读取的配置文件，已被 git 忽略。

## 2. 填哪些 Key、用哪些模型

### 2.1 最省事的方案（推荐先跑通）

| 项 | 值 |
|---|---|
| `EVAL_PROVIDER` | `deepseek` |
| `EVAL_API_KEY` | DeepSeek 控制台创建的 Key：<https://platform.deepseek.com/api_keys> |
| `EVAL_BASE_URL` | 留空（脚本用官方 OpenAI 兼容地址 `https://api.deepseek.com`；若 404 可手工改成 `https://api.deepseek.com/v1`） |
| `EVAL_MODEL` | 留空（脚本用 `deepseek-flash`；想更强可填 `deepseek-v4-pro`） |

DeepSeek 官方模型名以控制台/文档为准：`deepseek-flash`（快、便宜，适合先跑通）和
`deepseek-v4-pro`（更强，适合调度/审核）。参考：[DeepSeek API 文档](https://api-docs.deepseek.com/)。

### 2.2 交叉评测方案（至少两个 Key，比较模型差异）

| 供应商 | Key 申请 | Base URL（脚本预设） | 推荐模型（2026-10 文档） | 用途 |
|---|---|---|---|---|
| DeepSeek | <https://platform.deepseek.com/api_keys> | `https://api.deepseek.com` | `deepseek-flash` / `deepseek-v4-pro` | 基线；全链路 |
| 阿里云百炼 Qwen | <https://bailian.console.aliyun.com/> | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3.7-plus`（平衡）、`qwen3.8-flash`（便宜）、`qwen3.8-max`（更强） | 交叉；调度/审核 |
| 智谱 GLM | <https://bigmodel.cn/usercenter/proj-mgmt/apikeys> | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.3` / `glm-5.3-flash` | 交叉备选 |
| OpenAI | <https://platform.openai.com/api-keys> | `https://api.openai.com/v1` | 以控制台当前 chat 模型为准（脚本占位 `gpt-4.1-mini`） | 海外对照（可选） |

说明：
- Qwen 现在推荐使用带 WorkspaceId 的地域域名（如 `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`），
  旧域名 `https://dashscope.aliyuncs.com/compatible-mode/v1` 仍可用；两者 Key 必须属于同一地域。
  参考：[Alibaba Model Studio OpenAI 兼容文档](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)。
- 模型名会随供应商升级变化，以上是 2026-10 的官方文档推荐值；如果报 404「模型不存在」，
  到对应控制台的模型列表换成当前可用的 chat 模型名即可。

### 2.3 四个用途怎么分配

ParingBot 有四个模型用途，对应四个 Agent：

| 用途 | 职责 | 默认（省成本） | 想更稳（可选） |
|---|---|---|---|
| 调度 | 主管决定下一轮派谁 | `deepseek-flash` | `deepseek-v4-pro` / `qwen3.8-max` |
| 画像 | 从档案/动态提炼标签与依据 | `deepseek-flash` | `qwen3.7-plus` |
| 筛选 | 按偏好检索、写候选池 | `deepseek-flash` | `qwen3.7-plus` |
| 审核 | 双向评估 + 否决分类 | `deepseek-flash` | `deepseek-v4-pro` / `qwen3.8-max` |

如果四个用途想分开：在 `.env.eval` 里填：

```bash
EVAL_SCHEDULE_MODEL=deepseek-v4-pro
EVAL_PORTRAIT_MODEL=deepseek-flash
EVAL_SCREENER_MODEL=deepseek-flash
EVAL_AUDITOR_MODEL=deepseek-v4-pro
```

> 建议第一次先用统一 `deepseek-flash` 跑通，确认环境与链路没问题；再换强模型做对照。
> 不同模型/用途的结果要记录在报告 label 里，否则无法比较。

## 3. 成本与风险提示

- 一次真实匹配会产生**几十次模型调用**（主管循环 + 三个角色各自的工具循环），
  历史运行是 4–8 轮、39–84 次工具调用；token 量大约在**几万到十几万**量级。
  用 `deepseek-flash`/`qwen3.8-flash` 成本较低，强模型会明显更贵。
- 先用 `EVAL_TRIALS=1` 跑一次；不要一上来开多 trial。
- 真实运行会**新建匹配任务**（并消耗账号的候选池查询），但不修改租客档案；
  建议用 `member02`，避免覆盖 `member01` 的演示记录。
- 真实匹配受当前种子库数据、模型服务网络/限流影响；失败时先看管理端【调度时间线】与运行错误。
- 不要把 Key 写进 README、截图、代码或提交到 git。

## 4. 执行步骤

### 4.1 配置模型

```bash
# 编辑 .env.eval 填 EVAL_API_KEY 后：
python eval/configure_models.py
```

脚本会：
1. 登录管理员；
2. 把四个用途的启用配置更新成 `.env.eval` 指定的供应商/模型/Key（没有就新增一条「评测-用途模型」）；
3. 对每条配置调用一次真实连通性测试（只让模型回一个字）；
4. 打印结果；失败会告诉你先查地址/Key/模型名。

只打印计划、不写库：

```bash
python eval/configure_models.py --dry-run
```

### 4.2 跑真实匹配

```bash
python eval/run_live_eval.py
```

脚本会：
1. 登录管理员与评测租客；
2. 检查 `/match/my` 的前置条件，不满足时给出 blocker（例如 Key 没填）；
3. 调用 `POST /match/rerun` 发起真实匹配，轮询到结束；
4. 读取管理端调度详情（轮次、步骤、漏斗、工具调用）；
5. 在 `eval/reports/` 写 JSON + Markdown 报告，文件名包含 label 与时间戳。

多 trial：

```bash
python eval/run_live_eval.py --trials 2 --label deepseek-flash-baseline
```

### 4.3 换供应商做交叉

```bash
# 编辑 .env.eval：EVAL_PROVIDER=qwen，EVAL_API_KEY=...，EVAL_MODEL=qwen3.7-plus
python eval/configure_models.py
python eval/run_live_eval.py --label qwen3.7-plus-crosscheck
```

对比 `eval/reports/` 下两份报告：轮次、工具调用数、候选/通过/否决/交付、否决分类、
耗时、运行总结，以及人工阅读摘要的差异。

## 5. 报告里看什么

| 指标 | 含义 | 关注点 |
|---|---|---|
| `run_status` / `task_status` | 运行是否完成 | 失败先看 `error_message` |
| `total_round` | 调度轮次 | 过多轮次可能说明筛选/审核反复 |
| `timeline_steps` / `step_types` | 工具调用与角色步骤数 | 工具调用异常多可能是模型不收敛 |
| `funnel` | 筛出 → 否决 → 通过 → 交付 | 数字必须与候选/总结一致 |
| `counts` / `delivered` | 候选池与交付 | 交付为 0 要查放宽与审核 |
| `distribution` | 否决分类 | 硬条件冲突多说明偏好/池子问题 |
| `output_summary` | 主管收尾总结 | 人工阅读：解释是否合理、有没有对账噪声 |
| `wall_seconds` / `cost_millis` | 真实耗时 | 跨模型比较响应速度 |

> 这些是**过程指标**，不能单独证明「匹配质量好」。质量评价仍需人工看总结与候选，
> 或后续 `eval/run_eval.py --outputs` 的规则 / 人工 rubric。

## 6. 故障排查

| 现象 | 处理 |
|---|---|
| `EVAL_API_KEY` 为空 | 编辑 `.env.eval` 填入；`--dry-run` 不写库 |
| 401 / invalid key | 检查 Key、base_url、账号是否同地域；重新填 |
| 404 / model not found | 模型名与供应商文档对齐；DeepSeek 可试 `https://api.deepseek.com/v1`；Qwen 确认地域/WorkspaceId |
| 429 / rate limit | 降低并发（一次只跑一个 trial），等几分钟再试 |
| `/match/my` 前置检查被拦 | 按 blocker 提示处理；模型 Key 相关先跑 configure_models |
| 等很久不结束 | 默认 600s 超时；到管理端调度时间线看卡在哪一步，必要时重启后端（会标记失败） |
| 报告没有生成 | 看终端错误；`eval/reports/` 已被 gitignore |

## 7. 安全收尾

- `.env.eval` 与 `eval/reports/` 均被 git 忽略；
- Key 会写进演示库 `ai_model_config`（供后端调用），评测结束后如不再需要：
  - 到管理端【AI模型配置】把 Key 改掉/停用；或
  - 重建数据库卷（会清空演示数据）；
- 报告里只写模型名/供应商/Base URL，不写 Key。
