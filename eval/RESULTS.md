# 真实模型评测结果（2026-10-30）

> 环境：本机 Docker Compose 栈（`http://127.0.0.1:8080`），租客 `member02`，四个用途（调度/画像/筛选/审核）统一使用同一模型。
> 方式：`python eval/run_live_eval.py` → 真实发起 `/match/rerun` → 轮询到结束 → 读取管理端调度详情。
> 原始报告：`eval/reports/`（已 gitignore；不包含 API Key 与租客联系方式）。
> 说明：这是**过程评测**，记录轮次/候选/否决/交付/耗时/失败步骤；匹配质量仍需人工阅读运行总结与候选。

## 一、运行结果

| # | 模型 | max_tokens | 状态 | 轮次 | 候选 | 通过 | 否决 | 待审 | 交付 | 墙钟 | 工具调用 | 步骤 | 失败步骤 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | DeepSeek `deepseek-flash` | 2048 | ✅ 已完成 | 4 | 11 | 8 | 3 | 0 | 8 | 85.1s | 36 | 47 | 1 |
| 2 | DeepSeek `deepseek-flash` | 8192 | ✅ 已完成 | 11 | 42 | 10 | 32 | 0 | 8 | 360.5s | 124 | 157 | 8 |
| 3 | Qwen `qwen3.7-plus` | 2048 | ❌ 失败（输出截断） | 1 | 0 | 0 | 0 | 0 | 0 | 73s | 2 | 3 | 0 |
| 4 | Qwen `qwen3.7-plus` | 8192 | ❌ 失败（600s 超时） | 2 | 30 | 7 | 22 | — | — | 600s | 61 | 67 | — |
| 5 | Qwen `qwen3.7-plus` | 8192 | ❌ 失败（连接超时） | 5 | 41 | 7 | 30 | 4 | 7 | 945.7s | 88 | 103 | 1 |
| 6 | Qwen `qwen3.8-flash`（fallback） | 4096 | ✅ 已完成 | 7 | 13 | 8 | 5 | 0 | 8 | 780.4s | 56 | 76 | 14 |

> 第 4 次 600s 超时为首次尝试（未生成报告，数据来自数据库）；第 5 次在 945s 时失败，错误为「连不上接口地址」，属于模型服务网络/延迟问题，不是代码 crash。
> Qwen3.7-plus 的两次失败都发生在多轮/多批次处理中；Qwen3.8-flash 能完成，但比 DeepSeek 慢得多。

## 二、结论（针对本项目）

1. **DeepSeek `deepseek-flash` 可以作为当前评测基线**：两次真实运行都完成并交付 8/8；当前 Prompt/工具链在它上面可用。
2. **同一模型、同一配置下运行方差很大**：两次 DeepSeek 分别是 4 轮 / 11 候选 / 85 秒和 11 轮 / 42 候选 / 360 秒；单次运行不能代表质量，至少需要 3 次 trial 或固定更大的轮次/样本再比较。
3. **Qwen3.7-plus 在当前百炼 endpoint 上不适合直接做本项目的在线评测**：
   - 2048 max_tokens 时首个角色就因输出截断失败；
   - 提到 8192 后，一次 600s 超时、一次 945s 连接失败；5 轮共 41 候选、7 通过、30 否决，未能跑完；
   - 请求延迟明显高于 DeepSeek（88 次工具调用用了 945 秒），不适合当前 1200s 的评测预算。
4. **Qwen3.8-flash 可以作为快速替代做交叉**：能完成（7 轮 / 780 秒 / 13 候选 / 交付 8），但耗时约为 DeepSeek 第二次运行的 2 倍、第一次运行的 9 倍，且失败步骤 14 个（DeepSeek 8 个）；交叉评测时需要固定相同 max_tokens/超时/轮次上限，否则不可比。
5. **失败步骤暴露的是 Prompt/工具接口问题，不只是模型差异**：DeepSeek 第二次运行出现「search_members 连续 11 次被拦」「门店范围缺 store 参数」「一轮放宽多个维度」「放宽说明缺幅度」等错误；这些是下一轮 Prompt/工具说明优化的直接输入，不应只归因于模型。

## 三、建议的后续评测配置

- 基线模型：`deepseek-flash`（省钱、跑通）；重要评测可用 `deepseek-v4-pro` 做对照。
- 固定评测条件：同一 `EVAL_MAX_TOKENS`、同一 `MATCH_TIMEOUT_SECONDS`、同一 `SUPERVISOR_MAX_ROUND`、同一租客账号/种子数据；每个模型至少 3 trials。
- Qwen 交叉：优先用离本机更近的地域/Workspace endpoint，或 `qwen3.8-flash`；`qwen3.7-plus` 等端点稳定后再用。
- 每次运行后人工阅读 `output_summary` 与候选名单；过程指标（轮次/否决分布/失败步骤）只用于发现异常与回归。

## 四、可复现命令

```bash
# DeepSeek 基线（.env.eval）
python eval/configure_models.py --env-file .env.eval
python eval/run_live_eval.py --env-file .env.eval --label deepseek-flash-baseline

# Qwen 交叉（.env.eval.qwen）
python eval/configure_models.py --env-file .env.eval.qwen
python eval/run_live_eval.py --env-file .env.eval.qwen --label qwen3.7-plus-crosscheck
```

Qwen 3.7 超时/连接失败时，可先试 `.env.eval.qwen-flash`（qwen3.8-flash）；若仍失败，检查该 endpoint 的网络与地域，以及是否把 `EVAL_MAX_TOKENS`/`MATCH_TIMEOUT_SECONDS` 调够。
