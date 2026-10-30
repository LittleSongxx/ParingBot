#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 .env.eval 里的模型配置写进演示库的 ai_model_config 表，并做连通性测试。

为什么需要它：ParingBot 的模型 Key 不在运行时 .env 里，而在数据库
ai_model_config 表（管理端【AI模型配置】页）。评测前用这个脚本一次性把
四个用途（调度/画像/筛选/审核）切到评测用的供应商与模型，避免手点四遍。

用法：
  python eval/configure_models.py                # 读取 .env.eval
  python eval/configure_models.py --env-file .env.eval.qwen
  python eval/configure_models.py --dry-run      # 不联网，只打印计划
  python eval/configure_models.py --no-test      # 只写配置，不测连通性

安全：
  * .env.eval 已被 git 忽略；不要提交 Key；
  * 脚本只读 .env.eval，不打印完整 Key（只显示前 4 + 后 4 位）；
  * 写库的是演示环境的 ai_model_config，不是生产配置。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DEFAULT_ENV = REPO / ".env.eval"

PURPOSES = (
    ("调度", "EVAL_SCHEDULE_MODEL"),
    ("画像", "EVAL_PORTRAIT_MODEL"),
    ("筛选", "EVAL_SCREENER_MODEL"),
    ("审核", "EVAL_AUDITOR_MODEL"),
)

# 供应商预设。模型名会随供应商升级变化，填之前先看 RUNBOOK；
# 也可以只写 EVAL_PROVIDER=custom + EVAL_BASE_URL/EVAL_MODEL 自己指定。
PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",  # 官方 OpenAI 兼容地址；如 404 可试 /v1
        "model": "deepseek-flash",
        "alternatives": ["deepseek-v4-pro"],
        "key_url": "https://platform.deepseek.com/api_keys",
    },
    "qwen": {
        "label": "阿里云百炼",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.7-plus",
        "alternatives": ["qwen3.8-flash", "qwen3.8-max"],
        "key_url": "https://bailian.console.aliyun.com/",
    },
    "glm": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.3",
        "alternatives": ["glm-5.3-flash"],
        "key_url": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "alternatives": ["gpt-4o-mini"],
        "key_url": "https://platform.openai.com/api-keys",
    },
    "custom": {
        "label": "自定义网关",
        "base_url": "",
        "model": "",
        "alternatives": [],
        "key_url": "",
    },
}


def load_env(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"找不到 {path}；请先执行：cp .env.eval.example .env.eval 并填写")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def mask(key: str) -> str:
    key = key or ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "…" + key[-4:]


def request(app_base: str, method: str, path: str, token: str | None = None,
            payload: dict | None = None) -> dict:
    url = app_base.rstrip("/") + "/api" + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} 调用 {path} 失败：{detail[:300]}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"连不上 {url}：{exc}. 确认 Docker 栈已启动、EVAL_APP_BASE 正确")
    if body.get("code") != "200":
        raise SystemExit(f"{path} 返回业务错误：{body.get('code')} {body.get('msg')}")
    return body.get("data")


def login(app_base: str, username: str, password: str) -> str:
    data = request(app_base, "POST", "/login", payload={"username": username, "password": password})
    token = (data or {}).get("token")
    if not token:
        raise SystemExit("管理员登录失败：没有拿到 token")
    return token


def plan(env: dict, args) -> list[dict]:
    provider = args.provider or env.get("EVAL_PROVIDER", "deepseek")
    preset = PRESETS.get(provider)
    if preset is None:
        raise SystemExit(f"未知供应商 {provider!r}，可选：{', '.join(PRESETS)}")
    base_url = args.base_url or env.get("EVAL_BASE_URL") or preset["base_url"]
    model = args.model or env.get("EVAL_MODEL") or preset["model"]
    key = env.get("EVAL_API_KEY", "")
    if preset["label"] == "自定义网关" and not base_url:
        raise SystemExit("EVAL_PROVIDER=custom 时必须填 EVAL_BASE_URL")
    if not model:
        raise SystemExit("没有模型名：请填 EVAL_MODEL 或使用预设供应商")
    rows = []
    for purpose, env_name in PURPOSES:
        rows.append({
            "purpose": purpose,
            "model": env.get(env_name) or model,
            "base_url": base_url,
            "provider": preset["label"],
            "api_key": key,
        })
    return rows


def print_plan(rows: list[dict], env: dict, path: Path) -> None:
    print(f"配置文件：{path}")
    print(f"供应商：{rows[0]['provider']}  Base URL：{rows[0]['base_url']}")
    print(f"API Key：{mask(rows[0]['api_key']) or '（空，请填写 EVAL_API_KEY）'}")
    print("\n用途 -> 模型：")
    for row in rows:
        print(f"  {row['purpose']}：{row['model']}")
    print()


def configure(rows: list[dict], env: dict, test: bool) -> None:
    app_base = env.get("EVAL_APP_BASE", "http://127.0.0.1:8080")
    admin_user = env.get("EVAL_ADMIN_USERNAME", "admin")
    admin_pass = env.get("EVAL_ADMIN_PASSWORD", "admin123")
    token = login(app_base, admin_user, admin_pass)
    existing = request(app_base, "GET", "/aiModelConfig/selectPage?page_num=1&page_size=100", token=token) or {}
    configs = existing.get("list") or []
    by_purpose = {}
    for config in configs:
        by_purpose.setdefault(config.get("model_purpose"), []).append(config)

    results = []
    for row in rows:
        candidates = by_purpose.get(row["purpose"]) or []
        enabled = next((item for item in candidates if item.get("enabled") == "是"), None)
        target = enabled or (candidates[0] if candidates else None)
        payload = {
            "model_purpose": row["purpose"],
            "provider": row["provider"],
            "base_url": row["base_url"],
            "api_key": row["api_key"],
            "model_name": row["model"],
            "enabled": "是",
        }
        if target:
            payload.update({
                "id": target["id"],
                "name": target.get("name") or f"评测-{row['purpose']}模型",
                "temperature": target.get("temperature"),
                "max_tokens": target.get("max_tokens"),
            })
            request(app_base, "PUT", "/aiModelConfig/update", token=token, payload=payload)
        else:
            payload["name"] = f"评测-{row['purpose']}模型"
            request(app_base, "POST", "/aiModelConfig/add", token=token, payload=payload)
        # 重新取列表确认 id（新增后要测试连接）
        latest = request(app_base, "GET", "/aiModelConfig/selectPage?page_num=1&page_size=100", token=token) or {}
        matched = [item for item in latest.get("list", [])
                   if item.get("model_purpose") == row["purpose"] and item.get("enabled") == "是"]
        config_id = matched[-1]["id"] if matched else None
        outcome = "未测试"
        if test and config_id:
            try:
                outcome = request(app_base, "POST", f"/aiModelConfig/test/{config_id}", token=token) or "连通正常"
            except SystemExit as exc:
                outcome = f"失败：{exc}"
        results.append({**row, "config_id": config_id, "test": outcome})
    print("\n写入结果：")
    for item in results:
        print(f"  {item['purpose']:<4} config_id={item['config_id']} model={item['model']} test={item['test']}")
    print("\n下一步：python eval/run_live_eval.py")
    if any("失败" in str(item["test"]) for item in results):
        print("有连接测试失败：请核对 base_url/model，或先用管理端【AI模型配置】手工测试。")
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="写入评测模型配置（ai_model_config）")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--provider", choices=list(PRESETS), help="覆盖 EVAL_PROVIDER")
    parser.add_argument("--base-url", help="覆盖 EVAL_BASE_URL")
    parser.add_argument("--model", help="覆盖 EVAL_MODEL")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不登录/不写库")
    parser.add_argument("--no-test", action="store_true", help="不测连通性")
    args = parser.parse_args(argv)

    env = load_env(args.env_file)
    rows = plan(env, args)
    print_plan(rows, env, args.env_file)
    if not rows[0]["api_key"]:
        print("还没有填 EVAL_API_KEY。")
        print("  1) 编辑 .env.eval，填 EVAL_API_KEY=sk-...")
        provider = env.get("EVAL_PROVIDER", "deepseek")
        preset = PRESETS.get(provider) or {}
        if preset.get("key_url"):
            print(f"  2) {preset.get('label', provider)} API Key 申请：{preset.get('key_url', '')}")
        print("  3) 再执行 python eval/configure_models.py")
        return 2 if not args.dry_run else 0
    if args.dry_run:
        print("dry-run：未写库。")
        return 0
    configure(rows, env, test=not args.no_test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
