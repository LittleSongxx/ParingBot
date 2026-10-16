# Smartlect Assistant

The installable `smartlect` package provides a FastAPI entry, trusted Java cookie
sessions, confirmed transaction proposals and durable recovery.
Shopping runs bounded LangGraph ReAct with versioned skills, source citations,
owned memory and human handoff. The recommendation, attribution and
campaign/Merchant planes were retired by ADR-0008; only the scenario-scope and
retrieval-receipt contracts survive (no worker process remains). No model tool
can approve a transaction.

## Agent 架构（自上而下）

```
用户消息 → 准入闸 → MySQL 租约 → run_shopping（有界 ReAct 主循环）
  ├─ 系统提示 = AgentProfile 角色契约(profiles.py) + v28 策略叙事 + Skill 预告/澄清闸注入
  ├─ LangGraph 三节点图：model → tools → answer（ADR-0009 锁定语义）
  │    ├─ model：trim_messages 裁剪 + 真 token 流式（message_delta 增量 + replace 收口）
  │    ├─ tools：REGISTRY 单一注册表 → invoke() 五层设防（allowed→RBAC→Pydantic→
  │    │         幂等台账→gen_ai_span）；诚实边界观察投影（受理≠终态、查询≠办理）
  │    └─ answer：FinalAnswer 契约 + 守卫链 + compile_decision（模型只提议）
  ├─ task_dispatch → route_sub_agent 确定性分型路由 → 三个子智能体 profile
  │    （retrieval-scout / order-reader / comparator，各自收窄只读工具面）
  │    → create_react_agent 并发 → compose_results 确定性组装（部分失败显式披露）
  │    → 子工具调用走同一条 invoke()（无第二条更弱的路）
  └─ 关键分叉（澄清闸/子智能体路由/模板收口/修复轮）→ decision 事件 → SSE 透出
检索面：ES BM25 ∥ Qdrant ANN 并行召回 → RRF → vendor rerank；
       BackendHealth 滑动窗口健康度主动降权（skipped_degraded 可追溯）
```

决策记录：`../docs/adr/`（0003 控制面 / 0007 混检 / 0009 runtime / 0010 子智能体 /
0012 EchoMind 模式借鉴）。

```bash
python3.11 -m venv assistant/.venv
assistant/.venv/bin/python -m pip install -r assistant/requirements.lock
assistant/.venv/bin/python -m pip install --no-deps --no-build-isolation ./assistant
assistant/.venv/bin/python -m pip check
assistant/.venv/bin/python -m unittest discover -s assistant/tests -v
assistant/.venv/bin/python -m smartlect.app --check
assistant/.venv/bin/python -m smartlect.app
```

Any Python >=3.11 may replace `python3.11`; the current WSL verification uses
`/home/song/miniconda3/bin/python` (3.13.11) to create the clean virtual environment.
Run from the Smartlect root. `GET /health` listens on `127.0.0.1:18000` by default.
`SMARTLECT_ASSISTANT_HOST` and `SMARTLECT_ASSISTANT_PORT` change the bind address.
`SMARTLECT_MODEL_MODE` accepts `mock`, `rule-fallback`, or `live`.
Use `./scripts/dev.sh model-mode live` then `up` after configuring the provider.

Direct dependencies are declared in `pyproject.toml`; the single
`requirements.lock` pins their full closure, including MySQL RSA authentication
and the FastAPI/Pydantic/LangGraph stack plus bounded text-PDF parsing with pypdf.
The growth event consumer and its `SMARTLECT_ASSISTANT_EVENTS_ENABLED` switch were
retired with the attribution line (ADR-0008); retention cleanup now runs inside
the API process.

The launcher reads `run/runtime.env` and, for the Python application only,
the optional mode-600 `run/model.env`. The latter accepts only provider fields;
it cannot replace database, payment or internal authentication configuration.
These files are literal Python inputs, not shell scripts. F0 has copied the
authorized model fields and fixed `SMARTLECT_MODEL_ID=qwen3.7-plus`. See
`../docs/agent-design.md`, `../docs/adr/0001-final-integration.md` and
`../docs/history/integration-reuse.md` for decisions and source attribution.

Frozen source attribution and limitations are recorded in
`../docs/history/growth-migration.md`; original license material is under `licenses/`.
