"""Smartlect FastAPI, trusted sessions, durable proposals and read-only SSE replay."""
import argparse
import asyncio
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager
from decimal import Decimal
import hmac
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import Field, ValidationError
import uvicorn

from smartlect import __version__
from smartlect.auth import IdentityBridge
from smartlect.catalog_scope import product_scope
from smartlect.db import canonical
from smartlect.commerce import AsyncCommerceClient, CommerceError, CommerceRejected, ORDER_ACTION_STATUS_PATH
from smartlect.config import Settings
from smartlect.observability import gen_ai_span, prometheus_counter
from smartlect.agents.shopping.policy import SEMANTIC_RERANK_PROMPT as HOMEPAGE_RERANK_PROMPT

RUN_ADMISSION_REJECTIONS = prometheus_counter("assistant_run_admission_rejections_total",
                                              "New runs rejected by the concurrency admission gates", ["gate"])
FEEDBACK_SUBMISSIONS = prometheus_counter("assistant_feedback_total",
                                          "Answer feedback submissions per rating", ["rating"])
from smartlect import mcp
from smartlect.state import SessionStore, StateError
from smartlect.tools import Arguments, invoke
from smartlect.agents.shopping import run_shopping
from smartlect.session_focus import compile_focus
from smartlect.provider import IndexModelAudit, Provider, ProviderError, bounded
from smartlect.knowledge import KnowledgeStore
from smartlect.memory import MemoryStore
from smartlect.privacy import redact_text
from smartlect.documents import parse_document, MAX_INPUT_BYTES
from smartlect.adminscope import AdminScopeStore, ScopeSelectRequest


async def db(function, *args, **kwargs):
    return await asyncio.to_thread(function, *args, **kwargs)


log = logging.getLogger(__name__)


def _capture_structured_print():
    """把 [retrieve:...] / [route:...] 这类结构化 print 也落进 logging（uvicorn.error）。

    uvicorn 用默认 log config 启动，root logger 没有 handler——模块里 print 出来的
    轨迹在进程日志里看不到，等于没有观测面。只接管带前缀的那部分，其余 print
    （如 jieba 的加载信息）原样保留。
    """
    import builtins
    root = logging.getLogger("uvicorn.error")
    if not root.handlers:
        return
    original = builtins.print

    def wrapped(*args, **kwargs):
        text = " ".join(str(a) for a in args)
        if text.startswith("[retrieve:") or text.startswith("[route:"):
            root.info("%s", text)
        return original(*args, **kwargs)

    builtins.print = wrapped


class MessageRequest(Arguments):
    message_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8000)
    product_id: str | None = Field(default=None, max_length=64)
    sku_key: str | None = Field(default=None, max_length=256)
    focus_mode: Literal["GLOBAL", "PRODUCT", "GUIDE"] | None = None


class ProposalRequest(Arguments):
    message_id: str = Field(min_length=1, max_length=128)
    action_type: Literal["order", "cancel", "refund"]
    parameters: dict


class ConfirmRequest(Arguments):
    proposal_version: int = Field(ge=1)
    approved: bool = True


class ValueRequest(Arguments):
    value: str | int | list[str]


class PaymentRequest(Arguments):
    expected_amount_cents: int = Field(ge=0)


class TicketRequest(Arguments):
    action: Literal['take_over', 'reply', 'close']
    version: int = Field(ge=1)
    reply: str | None = Field(default=None, max_length=4000)


class KnowledgeRequest(Arguments):
    doc_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=40000)
    source_uri: str = Field(min_length=1, max_length=512)
    acl: Literal['PUBLIC', 'USER', 'MERCHANT', 'ACTOR']
    acl_actor_id: str | None = None
    valid_from: str
    valid_until: str
    language: Literal['zh-CN', 'en', 'mixed'] = 'zh-CN'
    product_ids: list[str] = Field(default_factory=list, max_length=100)
    category_ids: list[str] = Field(default_factory=list, max_length=100)
    facts: dict[str, str] = Field(default_factory=dict)


class FeedbackRequest(Arguments):
    rating: Literal["up", "down"]
    reason_code: Literal["irrelevant", "outdated", "citation_mismatch", "fabricated", "other"] | None = None
    reason_text: str | None = Field(default=None, max_length=2000)


def health(settings, config=None):
    config = os.environ if config is None else config
    model_ready = settings.model_mode != "live" or bool(
        config.get("SMARTLECT_MODEL_API_KEY") and config.get("SMARTLECT_MODEL_BASE_URL"))
    status = "ok" if model_ready else "misconfigured"
    return {"service": "smartlect-assistant", "version": __version__, "status": status,
            "phase": "F4", "model_mode": settings.model_mode,
            "model_ready": model_ready}


def _retention_loop(connect):
    """每日跑一次 purge_expired；连接缺失时仅休眠（无库环境不启动清理）。"""
    from smartlect.maintenance import purge_expired
    while True:
        if connect is not None:
            try:
                purge_expired(connect)
            except Exception:
                log.warning("retention purge failed", exc_info=True)
        time.sleep(86400)


async def execute_proposal(proposal, actor, commerce):
    action = proposal["action_type"]
    if action == 'payment':
        params = proposal['parameters']
        query = {'actionType': 'PAYMENT', 'params': {'payOrderId': params['payOrderId']}}
        current = await commerce.request('order', ORDER_ACTION_STATUS_PATH, actor=actor, data=query)
        if current.get('amountCents') != params['expected_amount_cents']:
            raise CommerceRejected(409, 'RECONFIRM_REQUIRED')
        mode = str(commerce.config.get('SMARTLECT_PAYMENT_MODE') or 'mock').lower()
        if mode == 'mock':
            if current.get('paymentStatus') == 'PENDING':
                await commerce.request('pay', '/internal/pay/mock/complete', actor=actor,
                                       data={'payOrderId': params['payOrderId'],
                                             'expectedAmountCents': params['expected_amount_cents']},
                                       key=proposal['idempotency_key'])
                current = await commerce.request('order', ORDER_ACTION_STATUS_PATH, actor=actor, data=query)
            return current
        if mode == 'live':
            # 实渠道：取支付宝表单交给前端拉起，服务端绝不代替用户完成真实支付；
            # 已支付(PENDING 之外)则只回状态，不再生成表单。
            if current.get('paymentStatus') == 'PENDING':
                pay = await commerce.request('pay', '/internal/pay/channel/getPayUrl', actor=actor, data={
                    'payChannel': 'alipay_pc',
                    'payOrderId': params['payOrderId'],
                    'subject': 'Smartlect 订单',
                    'amount': f"{Decimal(params['expected_amount_cents']) / 100:.2f}"})
                current = {**current, 'paymentMode': 'live', 'payChannel': 'alipay_pc',
                           'payInfo': (pay or {}).get('payInfo')}
            return current
        raise CommerceRejected(403, 'payment_mode_unsupported')
    kinds = {"order": "CREATE_ORDER", "cancel": "CANCEL_ORDER", "refund": "REFUND"}
    if action not in kinds:
        raise CommerceRejected(403, "action_not_allowed")
    params = proposal["parameters"]
    if proposal["recover_only"]:
        try:
            status = await commerce.request("order", ORDER_ACTION_STATUS_PATH, actor=actor, data={
                "actionType": kinds[action], "idempotencyKey": proposal["idempotency_key"],
                "params": {} if action == "order" else params})
        except CommerceRejected:
            # A rejected query says nothing about whether the prior write committed.
            raise CommerceError("commerce_outcome_unknown") from None
        if status.get("status") != "NOT_FOUND":
            return status
    if action == "order":
        return await commerce.request("order", "/internal/order/commerce/v2/createConfirmed", actor=actor,
                                      key=proposal["idempotency_key"], data={
                                          "quoteId": proposal["quote_id"], "confirmedAmountCents": proposal["quote_total_cents"],
                                          "order": params})
    return await commerce.request("order", "/internal/order/commerce/v2/executeAction", actor=actor,
                                  key=proposal["idempotency_key"], data={"actionType": kinds[action], "params": params})


def create_app(settings=None, *, config=None, store=None, identity=None, commerce=None,
               knowledge=None, memory=None, provider=None, adminscope=None, scenario_scope=None):
    settings = settings or Settings.from_env()
    config = dict(os.environ) if config is None else config
    # 无数据库环境（健康探针/纯静态模式）也允许启动：端点按需 503。
    if store is None and config.get("SMARTLECT_ASSISTANT_MYSQL_DATABASE"):
        store = SessionStore()
    if identity is None and config.get("SMARTLECT_VISITOR_SECRET"):
        identity = IdentityBridge(config, connect=store.connect if store else None)
    elif identity is not None and store is not None and getattr(identity, "connect", None) is None:
        identity.connect = store.connect
    commerce = commerce or AsyncCommerceClient(config)
    knowledge = knowledge or (KnowledgeStore(store.connect) if store else None)
    memory = memory or (MemoryStore(store.connect) if store else None)
    from smartlect.model_config import ModelConfigStore
    provider = provider or Provider(config, runtime_loader=ModelConfigStore(store.connect).loader() if store else None)
    adminscope = adminscope or (AdminScopeStore(store.connect) if store else None)
    from smartlect.scenario_scope import ScenarioScopeStore
    scenario_scope = scenario_scope or (ScenarioScopeStore(store.connect) if store else None)
    tasks = {}
    task_owners = {}  # run_id -> (subject_type, actor_id); admission counts live executors, not stale DB rows
    indexing = None
    actor_run_limit = bounded(config.get("SMARTLECT_ASSISTANT_RUNS_PER_ACTOR"), 3, 1, 64)
    global_run_limit = bounded(config.get("SMARTLECT_ASSISTANT_RUNS_GLOBAL"), 24, 1, 512)

    from smartlect import prompts as prompt_registry
    from smartlect.agents.shopping import PROMPT_VERSION as SHOPPING_PROMPT_VERSION, SYSTEM_POLICY_BODY
    from smartlect.business_skills import USER_SKILLS, load_skill
    prompt_registry.register_default('shopping', 'system_prompt', 'system', SYSTEM_POLICY_BODY,
                                     version=prompt_registry._code_version(SHOPPING_PROMPT_VERSION))
    prompt_registry.register_default('rerank', 'system_prompt', 'system', HOMEPAGE_RERANK_PROMPT,
                                     version=1)
    for domain, names in (('shopping', USER_SKILLS),):
        for skill_id in names:
            skill = load_skill(skill_id, domain=domain)
            prompt_registry.register_default(domain, 'skill', skill_id,
                                             json.dumps(skill, ensure_ascii=False),
                                             version=1)

    @asynccontextmanager
    async def lifespan(app):
        if store is not None:
            await db(store.initialize)
            prompt_registry.seed(store.connect)
        # 混合检索后端（ES/Qdrant）幂等建索引；未配置环境由 hybrid_search 内部跳过。
        try:
            from smartlect import hybrid_search
            # ensure_schema 是协程：直接 await（此前误经 db()=to_thread 包装，从未真正执行）
            await hybrid_search.ensure_schema()
        except Exception as error:
            # 建索引失败 = 知识/商品索引可能整层不可用（2026-10-08 线上因缺 aiohttp
            # 静默跳过全部 ES 检索，客服只能答"没有资料"）。这里必须吵，别只留 WARN。
            log.error("检索后端初始化失败（%s）：ES/Qdrant 索引将不可用，请检查依赖与配置",
                      type(error).__name__, exc_info=True)
        # 30 天数据保留任务原在 worker 进程；worker 退役后并入 API 进程（每日一跑，守护线程）。
        retention = threading.Thread(
            target=_retention_loop, name="smartlect-retention", daemon=True,
            kwargs={"connect": store.connect if store is not None else None})
        retention.start()
        if indexing is not None:
            await indexing.resume_stale()
        yield
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        if indexing is not None:
            indexing.shutdown()

    app = FastAPI(title="Smartlect AI API", version=__version__, lifespan=lifespan)

    async def admit_runs(actor):
        """Two gates before a new run starts executing: per-actor and global live-run
        counts. Idempotent replays of an already-running run never pass through here."""
        owner = (actor.subject_type, actor.actor_id)
        if sum(1 for held in task_owners.values() if held == owner) >= actor_run_limit:
            RUN_ADMISSION_REJECTIONS.labels("actor").inc()
            raise StateError("actor_run_limit", 429)
        if len(tasks) >= global_run_limit:
            RUN_ADMISSION_REJECTIONS.labels("global").inc()
            raise StateError("assistant_busy", 429)
    Instrumentator().instrument(app).expose(app, include_in_schema=False)

    # OTel 追踪（T1-7）：仅在显式配置端点且依赖可用时启用——未装包/未配置的
    # 环境（本地测试、CI）自动跳过，零影响。W3C traceparent 由 FastAPI/httpx
    # 插桩自动提取/注入，与 Java 侧 OTel javaagent 打通。
    def _instrument_otel():
        endpoint = config.get("SMARTLECT_OTEL_EXPORTER")
        if not endpoint:
            return
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            return
        provider = TracerProvider(resource=Resource.create({"service.name": "smartlect-assistant"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider,
                                            excluded_urls="health,metrics")
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)

    _instrument_otel()

    @app.middleware('http')
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        return response

    @app.exception_handler(StateError)
    async def state_error(request, error):
        return JSONResponse(status_code=error.status, content={"error": error.code})

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        # Rejected input may contain credentials. Return field locations only.
        return JSONResponse(status_code=422, content={"error": "invalid_request",
                            "fields": [list(item["loc"]) for item in error.errors()]})

    @app.exception_handler(CommerceRejected)
    async def commerce_rejected(request, error):
        return JSONResponse(status_code=409, content={"error": error.reason})

    @app.exception_handler(CommerceError)
    async def commerce_unknown(request, error):
        return JSONResponse(status_code=503, content={"error": "commerce_outcome_unknown"})

    @app.exception_handler(ProviderError)
    async def provider_error(request, error):
        return JSONResponse(status_code=503, content={'error': error.code})

    async def actor_for(request, response, *, write=False, user=False, realm="user"):
        if identity is None or store is None:
            raise HTTPException(503, "assistant_not_configured")
        actor = await identity.authenticate(request, response, realm=realm)
        if scenario_scope is not None:
            # demo 场景把已注册用户的 store scope 解析到其 execution_scope（无注册行时保持 store）
            actor = await db(scenario_scope.resolve_actor, actor)
        if adminscope is not None and actor.subject_type=='merchant':
            actor = await db(adminscope.selected_actor,actor)
        if user:
            if actor.subject_type != "user":
                raise HTTPException(401, "login_required")
        if write:
            identity.require_csrf(request, actor)
        return actor

    def assert_not_trial_user(actor):
        if actor.is_trial_user():
            raise HTTPException(403, "trial_read_only")

    async def assert_trial_chat_budget(actor):
        if not actor.is_trial_user():
            return
        if store is None:
            raise HTTPException(503, "assistant_not_configured")
        try:
            await db(store.increment_trial_chat, actor.actor_id)
        except StateError as error:
            if error.code == "trial_chat_limit":
                raise HTTPException(429, "trial_chat_limit") from None
            raise

    @app.get("/health")
    def get_health():
        result = health(settings, config)
        return JSONResponse(status_code=200 if result["status"] == "ok" else 503, content=result)

    @app.get("/api/assistant/session")
    async def session(request: Request, response: Response):
        actor = await actor_for(request, response)
        return {"actor": actor.model_dump(), "csrf_token": identity.csrf_token(actor), 'model_mode': settings.model_mode}

    @app.get("/api/assistant/catalog/scope")
    async def catalog_scope(request: Request, response: Response):
        actor = await actor_for(request, response)
        return await db(product_scope, store.connect, actor)

    @app.get("/admin-api/assistant/session")
    async def merchant_session(request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        return {"actor": actor.model_dump(), "csrf_token": identity.csrf_token(actor)}

    async def admin_actor(request, response, *, write=False):
        actor = await actor_for(request, response, realm='merchant', write=write)
        if write:
            actor.require('admin:legacy')
        else:
            actor.require_any('admin:legacy', 'admin:trial')
        return actor

    @app.get('/admin-api/assistant/scopes')
    async def merchant_scopes(request: Request,response: Response):
        actor=await admin_actor(request,response)
        return await db(adminscope.scopes,actor)

    @app.post('/admin-api/assistant/scopes/select')
    async def merchant_select_scope(payload: ScopeSelectRequest,request: Request,response: Response):
        actor=await admin_actor(request,response)
        actor.require('admin:legacy')
        identity.require_csrf(request,actor)
        selected=await db(adminscope.select_scope,actor,payload.execution_scope_id)
        return {'actor':selected.model_dump(),'csrf_token':identity.csrf_token(selected)}

    @app.post("/api/assistant/conversations")
    async def create_conversation(request: Request, response: Response, payload: Arguments):
        actor = await actor_for(request, response, write=True)
        await assert_trial_chat_budget(actor)
        return await db(store.create_conversation, actor)

    @app.get('/api/assistant/conversations')
    async def conversations(request: Request, response: Response):
        return await db(store.list_conversations, await actor_for(request, response))

    @app.get("/api/assistant/conversations/{conversation_id}")
    async def conversation(conversation_id: str, request: Request, response: Response):
        actor = await actor_for(request, response)
        result = await db(store.get_conversation, actor, conversation_id)
        result['handoff'] = await db(memory.handoff_state, actor, conversation_id)
        return result

    @app.post("/api/assistant/conversations/{conversation_id}/messages")
    async def message(conversation_id: str, payload: MessageRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True)
        await assert_trial_chat_budget(actor)
        text = redact_text(payload.text, request.cookies.values())
        run = await db(store.create_run, actor, conversation_id, payload.message_id, text, model_mode=settings.model_mode)
        # create_run checks exact idempotency before rejecting new messages under human control.
        run = await db(memory.recover_handoff_run, actor, run['agent_run_id']) or run
        if run['state'] in {'CREATED', 'RUNNING'} and run['agent_run_id'] not in tasks:
            await admit_runs(actor)
            try:
                lease = await db(store.claim_run, actor, run['agent_run_id'], owner='shopping-api', ttl_seconds=90)
            except StateError as error:
                if error.code in {'conversation_busy', 'run_deadline_exceeded'}:
                    return await db(store.get_run, actor, run['agent_run_id'])
                raise
            run = await db(store.get_run, actor, run['agent_run_id'])
            focus = compile_focus(product_id=payload.product_id, sku_key=payload.sku_key,
                                  focus_mode=payload.focus_mode)
            context = dict(run.get('context') or {})
            context.update(focus)
            await db(store.save_context, lease, context)
            run = {**run, 'context': context}

            async def execute():
                try:
                    with gen_ai_span(
                        "invoke_agent shopping",
                        kind="invoke_agent",
                        attributes={
                            "gen_ai.operation.name": "invoke_agent",
                            "gen_ai.agent.name": "shopping",
                            "session.id": run.get("conversation_id"),
                            "agent_run_id": run.get("agent_run_id"),
                        },
                    ):
                        await run_shopping(actor=actor, run=run, lease=lease, store=store, commerce=commerce,
                                           knowledge=knowledge, memory=memory, provider=provider,
                                           mode=settings.model_mode, config=config, scenario_scope_store=scenario_scope)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    log.exception("shopping_run_failed run=%s focus_product_id=%s",
                                  run.get("agent_run_id"), (run.get("context") or {}).get("focus_product_id"))
                    try:
                        await db(store.append_event, lease, 'error', {
                            'error_type': type(error).__name__,
                            'error': getattr(error, 'code', None) or str(error)[:240],
                        })
                        await db(store.finish_run, lease, state='FAILED', result={'error_type': type(error).__name__,
                                 'error': getattr(error, 'code', None) or 'assistant_failed',
                                 'model_mode': settings.model_mode})
                    except StateError:
                        pass  # A handoff/clear already fenced and cancelled this run.
            task = asyncio.create_task(execute())
            tasks[run['agent_run_id']] = task
            task_owners[run['agent_run_id']] = (actor.subject_type, actor.actor_id)
            task.add_done_callback(lambda _: (tasks.pop(run['agent_run_id'], None),
                                              task_owners.pop(run['agent_run_id'], None)))
        return run

    @app.post('/api/assistant/conversations/{conversation_id}/mcp')
    async def mcp_endpoint(conversation_id: str, payload: dict, request: Request, response: Response):
        """MCP JSON-RPC for the read-only tools, scoped to one conversation.

        The conversation is in the path rather than in the tool arguments so every MCP call
        lands in the same run/receipt trail as an agent call, with the same idempotency and
        permission checks. There is no second, weaker path into the tools. Transport is
        a single JSON-RPC POST, without session resumption or SSE.
        """
        actor = await actor_for(request, response, write=True)
        await admit_runs(actor)
        requested = (payload.get('params') or {}).get('protocolVersion') if isinstance(payload, dict) else None
        negotiated = mcp.negotiate(requested or request.headers.get('mcp-protocol-version'))
        response.headers['MCP-Protocol-Version'] = negotiated.protocol_version
        if negotiated.downgraded:
            response.headers['MCP-Protocol-Version-Downgraded'] = 'true'
            if negotiated.requested:
                response.headers['MCP-Protocol-Version-Requested'] = negotiated.requested
            response.headers['MCP-Supported-Protocol-Versions'] = ','.join(negotiated.supported)

        async def embed_query(query):
            if not config.get('SMARTLECT_EMBEDDING_API_KEY') or settings.model_mode != 'live':
                return {}
            result = await provider.embed([query], cacheable=True)
            meta = result['metadata']
            return {'query_vector': result['embeddings'][0], 'embedding_model': meta['model_id'],
                    'index_version': f"{meta['model_id']}:d{meta['dimensions']}:v1"}

        async def call_tool(name, arguments):
            if memory and await db(memory.handoff_state, actor, conversation_id):
                raise StateError('human_control_active', 409)
            run = await db(store.create_run, actor, conversation_id, 'mcp:' + uuid.uuid4().hex,
                           canonical({'mcp': name, 'arguments': arguments}), model_mode='rule-fallback')
            if run['state'] not in {'CREATED', 'RUNNING'}:
                raise StateError('run_not_resumable', 409)
            lease = await db(store.claim_run, actor, run['agent_run_id'], owner='mcp', ttl_seconds=30)
            try:
                receipt = await invoke(name, arguments, actor=actor, commerce=commerce, store=store, lease=lease,
                                       knowledge=knowledge, memory=memory, embed_query=embed_query,
                                       allowed=set(mcp.exposed_tools(actor)))
                await db(store.finish_run, lease, state='COMPLETED', result={'receipt': receipt})
                return receipt
            except Exception as error:
                await db(store.finish_run, lease, state='FAILED', result={'error_type': type(error).__name__})
                raise

        try:
            result = await mcp.handle(payload, actor=actor, call_tool=call_tool)
        except mcp.JsonRpcError as error:
            return JSONResponse(status_code=200, content=mcp.response(payload, error=error))
        if result is None:
            return Response(status_code=202)
        return mcp.response(payload, result=result)

    @app.post("/api/assistant/conversations/{conversation_id}/proposals")
    async def propose(conversation_id: str, payload: ProposalRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        actor.require("orders:write")
        if memory and await db(memory.handoff_state, actor, conversation_id):
            raise StateError('human_control_active', 409)
        run = await db(store.create_run, actor, conversation_id, payload.message_id,
                       canonical(payload.model_dump()), model_mode="rule-fallback")
        if run["state"] not in {"CREATED", "RUNNING"}:
            return run
        lease = await db(store.claim_run, actor, run["agent_run_id"], owner="api", ttl_seconds=30)
        try:
            name = "propose_" + payload.action_type
            await db(store.append_event, lease, "tool_started", {"name": name})
            scope = await db(product_scope, store.connect, actor)
            receipt = await invoke(name, payload.parameters, actor=actor, commerce=commerce, store=store, lease=lease,
                                   product_scope=scope)
            proposal = receipt["data"]
            await db(store.append_event, lease, "proposal_required", {"proposal": proposal})
            return await db(store.finish_run, lease, state="WAIT_USER", result={"proposal": proposal})
        except Exception as error:
            await db(store.append_event, lease, "error", {"error_type": type(error).__name__})
            await db(store.finish_run, lease, state="FAILED", result={"error_type": type(error).__name__})
            raise

    @app.get("/api/assistant/proposals/{proposal_id}")
    async def proposal(proposal_id: str, request: Request, response: Response):
        return await db(store.get_proposal, await actor_for(request, response), proposal_id)

    @app.get('/api/assistant/proposals/{proposal_id}/display')
    async def proposal_display(proposal_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, user=True)
        actor.require("orders:write")
        current = await db(store.get_proposal, actor, proposal_id)
        params = current['parameters']
        if current['action_type'] == 'refund':
            item = await commerce.request('order', '/internal/order/commerce/getOrderItem', actor=actor,
                                          data={'orderItemId': params['orderItemId']})
            if not item:
                raise HTTPException(404, 'order_item_not_found')
            return {'order': {'orderId': item['orderId'], 'items': [item]}}
        if current['action_type'] == 'cancel':
            order = await commerce.request('order', '/internal/order/commerce/getOrder', actor=actor,
                                           data={'orderId': params['orderId']})
            if not order:
                raise HTTPException(404, 'order_not_found')
            return {'order': order}
        raise HTTPException(422, 'proposal_has_no_existing_order')

    @app.post("/api/assistant/proposals/{proposal_id}/confirm")
    async def confirm(proposal_id: str, payload: ConfirmRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        actor.require("orders:write")
        return await confirm_owned(actor, proposal_id, payload)

    async def confirm_owned(actor, proposal_id, payload):
        current = await db(store.get_proposal, actor, proposal_id)
        if memory and await db(memory.handoff_state, actor, current['conversation_id']):
            raise StateError('human_control_active', 409)
        proposal = await db(store.confirm_proposal, actor, proposal_id, payload.proposal_version, approved=payload.approved)
        if proposal["status"] in {"REJECTED", "SUCCEEDED", "FAILED"}:
            return {"proposal": proposal}
        # Each HTTP invocation gets its own deadline; the confirmed proposal/action key stays unchanged.
        run = await db(store.create_run, actor, proposal["conversation_id"], f"confirm:{proposal_id}:{uuid.uuid4().hex}",
                       "用户确认已保存的交易提案", parent_run_id=proposal["agent_run_id"], model_mode="rule-fallback")
        lease = await db(store.claim_run, actor, run["agent_run_id"], owner="api", ttl_seconds=30)
        try:
            proposal = await db(store.begin_action, lease, proposal_id)
        except StateError as error:
            await db(store.finish_run, lease, state="FAILED", result={"error": error.code})
            raise
        if proposal["status"] in {"SUCCEEDED", "FAILED"}:
            return await db(store.finish_run, lease, state="COMPLETED", result={"proposal": proposal})
        try:
            receipt = await execute_proposal(proposal, actor, commerce)
            outcome = receipt.get("commandStatus", "unknown")
            if outcome not in {"business_completed", "business_pending", "command_accepted", "rejected", "unknown"}:
                outcome = "unknown"
        except CommerceRejected as error:
            outcome, receipt = "rejected", {"error": error.reason}
        except (CommerceError, TimeoutError):
            outcome, receipt = "unknown", {"error": "commerce_outcome_unknown"}
        proposal = await db(store.record_action_result, lease, proposal_id, outcome=outcome, receipt=receipt)
        terminal = proposal["status"] in {"SUCCEEDED", "FAILED"}
        await db(store.append_event, lease, "completed" if terminal else "operation_pending", {"proposal": proposal})
        return await db(store.finish_run, lease, state="COMPLETED" if terminal else "WAIT_OUTCOME", result={"proposal": proposal})

    @app.get('/api/assistant/payments/{pay_id}')
    async def payment_status(pay_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, user=True)
        actor.require("orders:write")
        result = await commerce.request('order', ORDER_ACTION_STATUS_PATH, actor=actor,
                                        data={'actionType': 'PAYMENT', 'params': {'payOrderId': pay_id}})
        return {**result, 'amount_cents': result.get('amountCents'),
                'payment_mode': str(config.get('SMARTLECT_PAYMENT_MODE') or 'mock').lower()}

    @app.post('/api/assistant/payments/{pay_id}/complete')
    async def complete_payment(pay_id: str, payload: PaymentRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        actor.require("orders:write")
        if str(config.get('SMARTLECT_PAYMENT_MODE') or 'mock').lower() == 'live' and actor.is_trial_user():
            # 实渠道模式下，只读访客身份不允许发起任何真实支付意图（建单已被 Java 侧
            # requireNonTrial 拦截，这里对支付提案创建再加一道对称防线）。
            raise HTTPException(403, 'trial_real_payment_disabled')
        current = await commerce.request('order', ORDER_ACTION_STATUS_PATH, actor=actor,
                                         data={'actionType': 'PAYMENT', 'params': {'payOrderId': pay_id}})
        if current.get('amountCents') != payload.expected_amount_cents:
            raise HTTPException(409, 'RECONFIRM_REQUIRED')
        conversation = await db(store.create_conversation, actor, identity_key='payment:' + pay_id)
        conversation = await db(store.get_conversation, actor, conversation['conversation_id'])
        proposals = [p for p in conversation['proposals'] if p['action_type'] == 'payment'
                     and p['status'] not in {'EXPIRED', 'REJECTED', 'FAILED'}]
        if proposals:
            proposal = proposals[0]
        else:
            run = await db(store.create_run, actor, conversation['conversation_id'], 'payment:' + uuid.uuid4().hex,
                           '用户点击确认模拟付款', model_mode='rule-fallback')
            lease = await db(store.claim_run, actor, run['agent_run_id'], owner='payment-api')
            proposal = await db(store.create_proposal, lease, action_type='payment',
                               parameters={'payOrderId': pay_id, 'expected_amount_cents': payload.expected_amount_cents},
                               expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
            await db(store.finish_run, lease, state='WAIT_USER', result={'proposal': proposal})
        confirmed = await confirm_owned(actor, proposal['proposal_id'], ConfirmRequest(
            proposal_version=proposal.get('decision_version') or proposal['version']))
        final = confirmed.get('proposal') or confirmed['result']['proposal']
        receipt = final.get('receipt') or {}
        return {**receipt, 'commandStatus': receipt.get('commandStatus', 'unknown'),
                'amount_cents': receipt.get('amountCents'), 'proposal_id': final['proposal_id']}

    @app.get('/api/assistant/preferences')
    async def preferences(request: Request, response: Response):
        return await db(memory.preferences, await actor_for(request, response, user=True))

    @app.put('/api/assistant/preferences/{key}')
    async def preference_update(key: str, payload: ValueRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        actor.require("orders:write")
        values = payload.value if isinstance(payload.value, list) else [payload.value]
        if any(isinstance(value, str) and redact_text(value, request.cookies.values()) != value for value in values):
            raise HTTPException(422, 'preference_contains_credentials')
        return await db(memory.set_preference, actor, key, payload.value)

    @app.delete('/api/assistant/preferences/{key}')
    async def preference_delete(key: str, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        actor.require("orders:write")
        return await db(memory.delete_preference, actor, key)

    @app.delete('/api/assistant/memory')
    async def clear_memory(request: Request, response: Response):
        actor = await actor_for(request, response, write=True)
        assert_not_trial_user(actor)
        return await db(memory.clear, actor)

    @app.post('/api/assistant/conversations/{conversation_id}/handoff')
    async def handoff(conversation_id: str, request: Request, response: Response, payload: Arguments):
        actor = await actor_for(request, response, write=True)
        assert_not_trial_user(actor)
        return await db(memory.handoff, actor, conversation_id, 'user_requested')

    @app.get('/api/assistant/knowledge/{doc_id}/{version}')
    async def reference(doc_id: str, version: int, request: Request, response: Response):
        return await db(knowledge.read_published_document, await actor_for(request, response), doc_id, version)

    @app.get('/admin-api/assistant/knowledge')
    async def documents(request: Request, response: Response):
        actor = await actor_for(request, response, realm='merchant')
        actor.require_any('admin:legacy', 'admin:trial')
        return await db(knowledge.list_documents, actor)

    @app.get('/admin-api/assistant/knowledge/{doc_id}/{version}')
    async def knowledge_document(doc_id: str, version: int, request: Request, response: Response):
        actor = await actor_for(request, response, realm='merchant')
        actor.require_any('admin:legacy', 'admin:trial')
        return await db(knowledge.get_document, actor, doc_id, version)

    @app.get('/admin-api/assistant/support')
    async def tickets(request: Request, response: Response):
        return await db(memory.list_tickets, await actor_for(request, response, realm='merchant'))

    @app.get('/admin-api/assistant/support/{ticket_id}')
    async def ticket_detail(ticket_id: str, request: Request, response: Response, before_sequence: int | None = None):
        actor = await actor_for(request, response, realm='merchant')
        return await db(memory.get_ticket, actor, ticket_id, before_sequence=before_sequence)

    @app.patch('/admin-api/assistant/support/{ticket_id}')
    async def ticket_update(ticket_id: str, payload: TicketRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, realm='merchant')
        return await db(memory.manage_ticket, actor, ticket_id, **payload.model_dump(exclude_none=True))

    @app.post('/admin-api/assistant/knowledge')
    async def draft(payload: KnowledgeRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, realm='merchant')
        actor.require('admin:legacy')
        if redact_text(payload.body, request.cookies.values()) != payload.body:
            raise HTTPException(422, 'document_contains_credentials')
        return await db(knowledge.create_draft, actor, payload.model_dump(exclude_none=True))

    @app.post('/admin-api/assistant/knowledge/parse')
    async def parse_file(filename: str, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, realm='merchant')
        actor.require('admin:legacy')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_INPUT_BYTES:
                raise HTTPException(413, 'document_input_too_large')
        result = await db(parse_document, filename, bytes(data))
        if redact_text(result['body'], request.cookies.values()) != result['body']:
            raise HTTPException(422, 'document_contains_credentials')
        return result

    @app.post('/admin-api/assistant/knowledge/{doc_id}/{version}/publish')
    async def publish(doc_id: str, version: int, request: Request, response: Response, payload: Arguments):
        actor = await actor_for(request, response, write=True, realm='merchant')
        actor.require('admin:legacy')
        document = await db(knowledge.get_document, actor, doc_id, version)
        if document['status'] == 'PUBLISHED':
            return await db(knowledge.publish, actor, doc_id, version)
        if document['status'] != 'DRAFT':
            raise HTTPException(409, 'document_not_draft')
        if indexing is not None and indexing.embedding_enabled():
            # Embedding runs as an async index job (smartlect/indexing.py): the request returns
            # a job immediately; progress is on /knowledgeIndex/jobs, publish happens when the
            # last batch lands. Without an embedding key the publish stays synchronous and
            # retrieval falls back to BM25-only, exactly as before.
            return await indexing.submit(actor, doc_id, version)
        published = await db(knowledge.publish, actor, doc_id, version)
        if indexing is not None:
            job = await db(indexing.record_sync_publish, actor, doc_id, version)
            if isinstance(published, dict):
                return {**published, "job_id": job["job_id"], "index_state": job["state"],
                        "index_message": job["message"]}
        return published

    @app.post('/admin-api/assistant/knowledge/{doc_id}/{version}/withdraw')
    async def withdraw(doc_id: str, version: int, request: Request, response: Response, payload: Arguments):
        actor = await actor_for(request, response, write=True, realm='merchant')
        actor.require('admin:legacy')
        return await db(knowledge.withdraw, actor, doc_id, version)

    @app.get("/api/assistant/runs/{run_id}")
    async def run_status(run_id: str, request: Request, response: Response):
        return await db(store.get_run, await actor_for(request, response), run_id)

    @app.post("/api/assistant/runs/{run_id}/feedback")
    async def run_feedback(run_id: str, payload: FeedbackRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True)
        result = await db(store.save_feedback, actor, run_id, payload.rating,
                          reason_code=payload.reason_code, reason_text=payload.reason_text)
        FEEDBACK_SUBMISSIONS.labels(payload.rating).inc()
        return result

    async def event_records(run_id: str, request: Request, response: Response):
        actor = await actor_for(request, response)
        await db(store.get_run, actor, run_id)
        try:
            after = int(request.headers.get("last-event-id", "0"))
            if after < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, "invalid_event_cursor") from None
        return actor, run_id, after, request

    @app.get("/api/assistant/runs/{run_id}/events", response_class=EventSourceResponse)
    async def events(parameters=Depends(event_records)) -> AsyncIterable[ServerSentEvent]:
        # Auth/ownership/cursor validation runs as a dependency before streaming headers.
        # Reconnection only replays persisted events, never starts or confirms a run.
        actor, run_id, after, request = parameters
        deadline = time.monotonic() + 95
        while time.monotonic() < deadline and not await request.is_disconnected():
            for event in await db(store.events, actor, run_id, after):
                after = event['sequence']
                yield ServerSentEvent(data=event, event=event['event_type'], id=str(after))
            run = await db(store.get_run, actor, run_id)
            if run['state'] not in {'CREATED', 'RUNNING'}:
                break
            await asyncio.sleep(0.5)

    indexing = None
    if store is not None:
        # Admin ops surface (runs browser, tool debug, index ops) lives in its own package;
        # app.py stays the composition root and only wires dependencies here.
        from smartlect import adminapi
        from smartlect.indexing import IndexingService
        from smartlect.shopping_retrieve import ShoppingRetrieve
        indexing = IndexingService(store.connect, knowledge, provider, settings=settings, config=config)
        adminapi.register(app, actor_for=actor_for, store=store, commerce=commerce, knowledge=knowledge,
                          provider=provider, config=config, settings=settings,
                          shopping_retrieve=ShoppingRetrieve(commerce), indexing=indexing)

    return app


def main():
    parser = argparse.ArgumentParser(description="Smartlect AI API")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.check:
        print(json.dumps(health(settings)))
        return
    _capture_structured_print()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, ws="none", access_log=False)


if __name__ == "__main__":
    main()
