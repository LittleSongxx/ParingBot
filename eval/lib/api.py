"""评测 HTTP 客户端与账号/运行等待逻辑（从旧 runner 抽取）。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

INFLIGHT = ("运行中", "待执行", "执行中")
BALANCE_HINTS = ("余额", "额度不足", "insufficient", "quota", "402")
PASSWORD = "Eval2026!"
ACCOUNT_PREFIX = "TEST_SCENARIO_"


class Api:
    def __init__(self, app_base: str):
        self.base = app_base.rstrip("/") + "/api"

    def call(self, method: str, path: str, token: str | None = None,
             payload: dict | None = None, timeout: int = 120) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["token"] = token
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                return json.loads(body)
            except ValueError:
                return {"code": str(exc.code), "msg": body[:300], "_http": exc.code}
        except urllib.error.URLError as exc:
            raise SystemExit(f"连不上 {self.base}：{exc}. 确认 Docker 栈已启动")

    def data(self, method: str, path: str, token: str | None = None,
             payload: dict | None = None, timeout: int = 120):
        body = self.call(method, path, token=token, payload=payload, timeout=timeout)
        if str(body.get("code")) != "200":
            raise RuntimeError(f"{method} {path} 业务失败：{body.get('code')} {body.get('msg')}")
        return body.get("data")


def login(api: Api, username: str, password: str) -> str:
    data = api.data("POST", "/login", payload={"username": username, "password": password})
    token = (data or {}).get("token")
    if not token:
        raise RuntimeError("登录失败：没有拿到 token")
    return token


def ensure_account(api: Api, account: str, reuse: bool) -> tuple[str, str]:
    """返回 (token, 账号动作说明)。新账号先注册，已存在就直接登录。"""
    if reuse:
        return login(api, account, "123456"), "复用已有演示账号，未改动其档案"
    if not account.startswith(ACCOUNT_PREFIX):
        raise RuntimeError(f"拒绝为非 {ACCOUNT_PREFIX} 账号建数据：{account}")
    body = api.call("POST", "/register",
                    payload={"username": account, "password": PASSWORD, "confirmPassword": PASSWORD})
    if str(body.get("code")) == "200":
        note = "本次新注册"
    elif "已存在" in str(body.get("msg") or ""):
        note = "账号已存在，本次复用"
    else:
        raise RuntimeError(f"注册 {account} 失败：{body.get('code')} {body.get('msg')}")
    return login(api, account, PASSWORD), note


# --------------------------------------------------------------------------
# 场景准备
# --------------------------------------------------------------------------
def save_profile(api: Api, token: str, item: dict) -> dict:
    return api.data("POST", "/member/saveMy", token=token, payload=item)


def save_preference(api: Api, token: str, item: dict) -> dict:
    return api.data("POST", "/preference/saveMy", token=token, payload=item)


def ensure_moments(api: Api, token: str, contents: list[str]) -> dict:
    """动态只发一次：重复跑脚本时不重复发布，保证同一场景的画像输入稳定。"""
    page = api.data("GET", "/moment/selectMyPage?page_num=1&page_size=10", token=token) or {}
    existing = page.get("total") or 0
    if existing or not contents:
        return {"published": 0, "existing": existing}
    for text in contents:
        api.data("POST", "/moment/publish", token=token,
                 payload={"content": text, "visible": "公开", "image_paths": []})
    page = api.data("GET", "/moment/selectMyPage?page_num=1&page_size=10", token=token) or {}
    return {"published": len(contents), "existing": page.get("total") or 0}


def readiness_of(api: Api, token: str) -> dict:
    return api.data("GET", "/match/my", token=token) or {}


# --------------------------------------------------------------------------
# 运行
# --------------------------------------------------------------------------
def wait_idle(api: Api, token: str, timeout: int = 1300, poll: int = 5) -> dict:
    deadline = time.time() + timeout
    while True:
        my = readiness_of(api, token)
        run = (my.get("run") or {})
        if run.get("run_status") not in INFLIGHT:
            return my
        if time.time() > deadline:
            raise RuntimeError(f"等待上一次运行结束时超时：仍在 {run.get('run_status')}")
        time.sleep(poll)


def wait_run(api: Api, token: str, run_id: int, timeout: int, poll: int) -> tuple[dict, float]:
    started = time.time()
    deadline = started + timeout
    last = None
    while True:
        my = readiness_of(api, token)
        run = my.get("run") or {}
        status = run.get("run_status")
        if status != last:
            print(f"    · {run.get('run_no') or run_id} -> {status}")
            last = status
        if run.get("id") == run_id and status not in INFLIGHT:
            return my, round(time.time() - started, 2)
        if time.time() > deadline:
            return my, round(time.time() - started, 2)
        time.sleep(poll)
