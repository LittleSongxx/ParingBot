#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景矩阵评测：不同申请人画像 × 真实多 Agent 匹配，横向对比。

它回答的问题不是「匹配好不好」，而是「换个申请人，这条流水线还跑得动吗」：
短租/长租、养宠/吸烟、预算紧/跨门店、档案残缺、池子里没有兼容候选——
每个场景都真实建档案、真实看 readiness、真实发起 /match/rerun 并轮询到结束。

约束：
  * 只走业务接口（注册/登录/档案/偏好/动态/匹配/调度详情），不改业务代码、不改 eval/cases；
  * 新建账号一律 TEST_SCENARIO_ 前缀，且保持「待审核」状态——未通过审核的档案
    不会进入候选池，所以这些场景申请人不会污染其他场景的候选池；
  * member02 只读复用（不改它的档案/偏好/动态），用来做短租基线；
  * 负向场景（档案残缺）不调用模型：只读 readiness + 试一次 /match/rerun 看是否被拒。

用法：
  python eval/scenario_matrix.py --phase ready             # 只跑前置检查（不花 token）
  python eval/scenario_matrix.py --only S1,S3 --trials 2   # 指定场景、指定 trial 数
  python eval/scenario_matrix.py                           # 全矩阵（会真实消耗模型 Token）
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DEFAULT_ENV = REPO / ".env.eval"
REPORTS = ROOT / "reports"

# 运行中的状态，出现这三个都还没结束
INFLIGHT = ("运行中", "待执行", "执行中")
# 模型侧余额/额度用尽的关键词：命中就停掉整批场景，不要继续烧
BALANCE_HINTS = ("余额", "额度不足", "insufficient", "quota", "402")
# 新建场景账号的统一口令（只在本机评测库使用，不落任何配置文件）
PASSWORD = "Eval2026!"
ACCOUNT_PREFIX = "TEST_SCENARIO_"


# --------------------------------------------------------------------------
# 场景定义
# --------------------------------------------------------------------------
def profile(nickname, gender, birth_date, rent_budget, tidiness, occupation,
            lease_term, store_id, schedule_type, has_pet, smoking,
            self_intro, roommate_expectation, interest_tags=None):
    return {
        "nickname": nickname, "gender": gender, "birth_date": birth_date,
        "rent_budget": rent_budget, "tidiness": tidiness, "occupation": occupation,
        "lease_term": lease_term, "store_id": store_id, "schedule_type": schedule_type,
        "has_pet": has_pet, "smoking": smoking, "self_intro": self_intro,
        "roommate_expectation": roommate_expectation,
        "interest_tags": interest_tags or [],
    }


def pref(age_min, age_max, age_required="必须", budget_min=800, budget_max=20000,
         budget_required="加分", tidiness_min="随意", tidiness_required="加分",
         store_scope="不限", store_required="加分", schedule_accept=("正常作息",),
         schedule_required="必须", lease_min="不限", lease_required="加分",
         pet_accept="无所谓", pet_required="加分"):
    return {
        "age_min": age_min, "age_max": age_max, "age_required": age_required,
        "budget_min": budget_min, "budget_max": budget_max, "budget_required": budget_required,
        "tidiness_min": tidiness_min, "tidiness_required": tidiness_required,
        "store_scope": store_scope, "store_required": store_required,
        "schedule_accept": list(schedule_accept), "schedule_required": schedule_required,
        "lease_min": lease_min, "lease_required": lease_required,
        "pet_accept": pet_accept, "pet_required": pet_required,
    }


SCENARIOS = [
    {
        "key": "S1", "account": "member02", "reuse": True, "trials": 3, "run": True,
        "title": "短租（3个月以下）基线",
        "expect": "可运行并交付（池内已补短租候选）",
        "why": "演示账号禾瑾：女/26/4000 元/整洁/3个月以下/张江店；偏好必须项=年龄 23-30 + 作息",
        "profile": None, "preference": None, "moments": [],
    },
    {
        "key": "S2", "account": ACCOUNT_PREFIX + "LONG12", "reuse": False, "trials": 1, "run": True,
        "title": "长租 1-2 年",
        "expect": "可运行；候选多为中长租",
        "why": "租期另一侧：女/28/3600 元/整洁/1-2年/中山北路店(20)；偏好租期下限 1-2 年（加分）",
        "profile": profile(
            "沈知远", "女", "1997-06-12", 3600, "整洁", "产品经理", "1-2年", 20,
            "正常作息", "无", "不吸烟",
            "在中山北路一带做产品经理，打算长住一年以上。作息比较规律，十二点半前睡。"
            "周末喜欢在家做饭、看纪录片，公共区域用完会收拾干净。不吸烟，也没有养宠物。",
            "希望室友作息规律、爱干净，能接受偶尔一起做饭；希望长租，别住几个月就搬，"
            "尽量在同一家门店附近。",
            ["看电影", "看纪录片"],
        ),
        "preference": pref(
            25, 33, budget_min=3000, budget_max=4200, tidiness_min="整洁",
            store_scope="同门店", schedule_accept=("正常作息", "早睡早起"),
            lease_min="1-2年",
        ),
        "moments": [
            "这个月开始认真看长租的房子，打算至少住一年，不想再折腾搬家了。",
            "周末在家做了三菜一汤，厨房擦得比较干净，锅具都归位了。",
        ],
    },
    {
        "key": "S3", "account": ACCOUNT_PREFIX + "LONG2Y", "reuse": False, "trials": 2, "run": True,
        "title": "长租 2 年以上",
        "expect": "可运行；验证长租另一端与交付稳定性",
        "why": "男/31/3200 元/一般/2年以上/中山北路店(20)；夜猫子、预算与年龄都设必须项",
        "profile": profile(
            "程亦舟", "男", "1994-09-03", 3200, "一般", "后端工程师", "2年以上", 20,
            "夜猫子", "无", "不吸烟",
            "程序员，在中山北路附近上班，准备长租两年以上。加班比较多，通常一两点睡，"
            "早上起得晚，晚上会在客厅敲会儿键盘但戴耳机。东西不算特别整齐，但不会堆垃圾。",
            "希望室友能接受晚睡晚起的作息，晚上别太吵；长租优先，至少一年以上。",
            ["主机游戏", "听音乐"],
        ),
        "preference": pref(
            26, 36, budget_min=2800, budget_max=4000, budget_required="必须",
            tidiness_min="一般", store_scope="同门店",
            schedule_accept=("夜猫子", "正常作息"), schedule_required="加分",
            lease_min="2年以上",
        ),
        "moments": [
            "连着加了一周班，回来基本就是洗漱睡觉，客厅灯都懒得开。",
            "打算在这儿长住两年，把显示器和椅子都搬过来了。",
        ],
    },
    {
        "key": "S4", "account": ACCOUNT_PREFIX + "PET", "reuse": False, "trials": 1, "run": True,
        "title": "养宠（has_pet=有）",
        "expect": "可运行；候选需接受室友养宠",
        "why": "女/27/3500 元/一般/6-12个月/桃浦店(19)；养猫，偏好里「接受」室友养宠",
        "profile": profile(
            "林小满", "女", "1998-03-18", 3500, "一般", "幼儿园老师", "6-12个月", 19,
            "正常作息", "有", "不吸烟",
            "在幼儿园当老师，养了一只三岁的橘猫叫「团子」，很乖、已绝育、会自己用猫砂盆。"
            "作息正常，十一点睡，周末会打扫一遍房间。猫不进屋乱翻，但掉毛是没办法的事。",
            "希望室友不排斥猫，能接受偶尔有猫毛；如果不喜欢猫提前说，我可以把猫留在自己房间。"
            "希望作息规律，公共区域一起保持干净。",
            ["养猫", "撸猫"],
        ),
        "preference": pref(
            24, 33, budget_min=3000, budget_max=4200, tidiness_min="一般",
            store_scope="同片区", schedule_accept=("正常作息", "早睡早起"),
            lease_min="6-12个月", pet_accept="接受",
        ),
        "moments": [
            "团子今天把我的毛线球拆了，收拾了半天，猫倒是睡得很香。",
            "周末给猫砂盆彻底换了一遍，房间也拖了地，闻不到味道。",
            "带团子去打了疫苗，医生说体重很标准。",
        ],
    },
    {
        "key": "S5", "account": ACCOUNT_PREFIX + "SMOKE", "reuse": False, "trials": 1, "run": True,
        "title": "吸烟（偶尔）+ 期望不在屋里抽",
        "expect": "可运行；审核官需按「吸烟偶尔」与室友期望双向判断",
        "why": "男/29/3300 元/整洁/6-12个月/真如店(18)；smoking=偶尔，自述只在阳台抽",
        "profile": profile(
            "许明川", "男", "1996-11-07", 3300, "整洁", "销售", "6-12个月", 18,
            "正常作息", "无", "偶尔",
            "做销售的，应酬多，烟瘾不重，一周抽两三根，只在阳台抽、开窗、烟头自己收。"
            "屋里从来不抽。作息比较正常，十二点前睡，房间保持整洁。",
            "希望室友不在屋里抽烟，阳台可以；如果室友完全不吸烟更好，我不会把烟味带进屋。"
            "希望作息规律、爱干净。",
            ["看电影", "听音乐"],
        ),
        "preference": pref(
            25, 35, budget_min=2800, budget_max=4000, tidiness_min="整洁",
            store_scope="同门店", schedule_accept=("正常作息",),
            lease_min="6-12个月",
        ),
        "moments": [
            "应酬完回来有点晚，在阳台抽了一根才进屋，怕把烟味带进客厅。",
            "把阳台的烟灰缸洗了，窗台也擦了，屋里闻不出味道。",
        ],
    },
    {
        "key": "S6", "account": ACCOUNT_PREFIX + "BUDGET", "reuse": False, "trials": 1, "run": True,
        "title": "预算偏紧（2500-2800）",
        "expect": "可运行；验证预算两端偏紧时候选是否够",
        "why": "女/25/2500 元/一般/3-6个月/张江店(1)；偏好预算 2500-2800 设为必须项",
        "profile": profile(
            "周清和", "女", "2000-08-22", 2500, "一般", "客服专员", "3-6个月", 1,
            "正常作息", "无", "不吸烟",
            "在张江做客服，刚换工作，预算比较紧，能接受 2500 左右的房间。作息正常，"
            "平时不太做饭，主要点外卖，公共区域用完会收拾。不吸烟、不养宠物。",
            "希望房租别太贵，预算 2600 以内；希望室友作息正常、爱干净，晚上别太吵。",
            ["追剧", "听音乐"],
        ),
        "preference": pref(
            22, 30, budget_min=2500, budget_max=2800, budget_required="必须",
            tidiness_min="一般", store_scope="同门店",
            schedule_accept=("正常作息", "早睡早起"), schedule_required="加分",
            lease_min="3-6个月",
        ),
        "moments": [
            "刚换工作，工资还没发，这个月基本靠外卖凑合，预算得省着点。",
            "下班回来把房间收拾了一遍，东西不多，好归置。",
        ],
    },
    {
        "key": "S7", "account": ACCOUNT_PREFIX + "FARSTORE", "reuse": False, "trials": 1, "run": True,
        "title": "跨区/远门店（store_id=20 中山北路店）",
        "expect": "可运行；验证同门店硬范围下的候选供给",
        "why": "男/30/3000 元/整洁/6-12个月/中山北路店(20)；门店范围设必须「同门店」",
        "profile": profile(
            "顾承泽", "男", "1995-05-14", 3000, "整洁", "物流主管", "6-12个月", 20,
            "正常作息", "无", "不吸烟",
            "在物流公司做主管，常驻中山北路店附近，通勤骑车十分钟。作息正常，"
            "爱干净，公共区域会主动打扫。不吸烟、不养宠物，周末偶尔做顿饭。",
            "希望就在中山北路店附近，通勤方便；希望室友作息正常、干净，别半夜吵闹。",
            ["看电影", "看纪录片"],
        ),
        "preference": pref(
            26, 35, budget_min=2800, budget_max=4000, tidiness_min="整洁",
            store_scope="同门店", store_required="必须",
            schedule_accept=("正常作息",), schedule_required="加分",
            lease_min="6-12个月",
        ),
        "moments": [
            "搬到中山北路这边上班，通勤十分钟，想就近找房子。",
            "周末把公共区域拖了一遍，垃圾桶也倒了。",
        ],
    },
    {
        "key": "S8", "account": ACCOUNT_PREFIX + "NOMOMENT", "reuse": False, "trials": 0, "run": False,
        "title": "档案不完整：有档案/偏好、无动态",
        "expect": "readiness 在「租客动态」阻断，不调用模型",
        "why": "档案与偏好都完整，故意不发动态；验证 moment 检查与 /match/rerun 拒绝",
        "profile": profile(
            "苏念安", "女", "1999-12-01", 3400, "整洁", "会计", "6-12个月", 5,
            "正常作息", "无", "不吸烟",
            "在漕河泾做会计，作息正常、爱干净，不吸烟不养宠物，周末一般在家看书。",
            "希望室友作息规律、干净，最好同门店通勤。",
            [],
        ),
        "preference": pref(
            23, 32, budget_min=3000, budget_max=4000, tidiness_min="整洁",
            store_scope="同门店", schedule_accept=("正常作息",),
        ),
        "moments": [],
        "probe_rerun": True,
    },
    {
        "key": "S9", "account": ACCOUNT_PREFIX + "NOPROFILE", "reuse": False, "trials": 0, "run": False,
        "title": "档案不完整：只注册、无任何档案",
        "expect": "readiness 在「租客档案」阻断，不调用模型",
        "why": "只有账号，profile/preference/moment 全空；验证第一项检查与 /match/rerun 拒绝",
        "profile": None, "preference": None, "moments": [],
        "probe_rerun": True,
    },
    {
        "key": "S10", "account": ACCOUNT_PREFIX + "LEASEPOOL", "reuse": False, "trials": 1, "run": True,
        "title": "池中无可用候选（租期看似兼容、硬筛后为空）",
        "expect": "预期 readiness lease_pool 阻断；实际以运行结果为准",
        "why": "男/34/2年以上/中山北路店(20)，年龄必须项设 18-18 岁（种子池最小 22 岁）→ 硬筛必空",
        "profile": profile(
            "邵怀瑾", "男", "1992-02-09", 3400, "整洁", "法务顾问", "2年以上", 20,
            "正常作息", "无", "不吸烟",
            "做法务顾问，准备在中山北路长租两年以上。作息正常，房间整洁，不吸烟不养宠物。",
            "希望室友年龄跟我差不多、作息正常、干净，长租优先。",
            [],
        ),
        "preference": pref(
            18, 18, budget_min=3000, budget_max=4500, tidiness_min="整洁",
            store_scope="同门店", store_required="必须",
            schedule_accept=("正常作息",), schedule_required="加分",
            lease_min="2年以上",
        ),
        "moments": [
            "最近在对比中山北路附近的长租房源，打算一次签两年。",
        ],
    },
    {
        "key": "S11", "account": ACCOUNT_PREFIX + "LEASEHARD", "reuse": False, "trials": 1, "run": True,
        "title": "租期硬冲突（申请方短租、候选必须 2 年以上）",
        "expect": "候选能找到但都被租期硬规则否决，最终 0 交付",
        "why": "女/26/3个月以下/张江店(1)，偏好「最短租期 2 年以上」设必须 → 档位差 4 ≥2 全否决",
        "profile": profile(
            "孟抒宜", "女", "1999-04-25", 3800, "整洁", "新媒体运营", "3个月以下", 1,
            "正常作息", "无", "不吸烟",
            "做新媒体运营，近期是过渡期，先住两三个月看看。作息正常、爱干净，不吸烟不养宠物。",
            "希望室友作息规律、爱干净，租期能长一点更稳定。",
            ["追剧", "看电影"],
        ),
        "preference": pref(
            25, 35, budget_min=3200, budget_max=4800, tidiness_min="整洁",
            store_scope="同门店", schedule_accept=("正常作息",),
            lease_min="2年以上", lease_required="必须",
        ),
        "moments": [
            "这两个月先找个过渡的房子，行李不多，随时能搬。",
        ],
    },
]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def load_env(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"找不到 {path}；请先 cp .env.eval.example .env.eval 并填写")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


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


def run_trial(api: Api, admin: str, token: str, timeout: int, poll: int, index: int) -> dict:
    wait_idle(api, token, timeout=timeout, poll=poll)
    print(f"  trial {index}: 发起 /match/rerun")
    created = api.data("POST", "/match/rerun", token=token) or {}
    run_id = created.get("run_id")
    if not run_id:
        return {"trial": index, "fatal": f"没有拿到 run_id：{created}"}
    my, wall = wait_run(api, token, run_id, timeout, poll)
    run = my.get("run") or {}
    task = my.get("task") or {}
    detail = {}
    try:
        detail = api.data("GET", f"/trace/detail?run_id={run_id}", token=admin) or {}
    except Exception as exc:  # noqa: BLE001 调度详情只是加分项，取不到不阻断
        detail = {"error": str(exc)}
    stat = detail.get("stat") or {}
    step_types: dict = {}
    for step in detail.get("timeline") or []:
        key = step.get("step_type") or "未知"
        step_types[key] = step_types.get(key, 0) + 1
    return {
        "trial": index,
        "run_id": run_id,
        "run_no": run.get("run_no") or created.get("run_no"),
        "task_id": task.get("id"),
        "task_no": task.get("task_no") or created.get("task_no"),
        "task_status": task.get("status"),
        "run_status": run.get("run_status"),
        "already_running": created.get("already_running"),
        "total_round": run.get("total_round"),
        "cost_millis": run.get("cost_millis"),
        "wall_seconds": wall,
        "counts": my.get("counts"),
        "delivered": my.get("delivered"),
        "distribution": [row for row in (my.get("distribution") or []) if row.get("count")],
        "note": my.get("note"),
        "output_summary": run.get("output_summary"),
        "error_message": run.get("error_message"),
        "funnel": detail.get("funnel"),
        "stat": stat,
        "step_types": step_types,
        "rounds": len(my.get("rounds") or []),
        "round_rows": my.get("rounds") or [],
    }


def balance_hit(trial: dict) -> str | None:
    text = " ".join(str(trial.get(key) or "") for key in
                    ("error_message", "output_summary", "note", "fatal"))
    for hint in BALANCE_HINTS:
        if hint.lower() in text.lower():
            return hint
    return None


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run_scenario(api: Api, admin: str, scenario: dict, args, env: dict) -> dict:
    key = scenario["key"]
    print(f"\n=== {key} {scenario['title']} ===")
    record = {
        "key": key,
        "title": scenario["title"],
        "account": scenario["account"],
        "expect": scenario["expect"],
        "why": scenario["why"],
        "trials_planned": scenario.get("trials", 0),
        "notes": [],
        "runs": [],
    }
    token, note = ensure_account(api, scenario["account"], scenario.get("reuse", False))
    record["account_note"] = note
    print(f"  账号：{scenario['account']}（{note}）")

    if scenario.get("profile"):
        save_profile(api, token, scenario["profile"])
        record["notes"].append("档案已保存")
    if scenario.get("preference"):
        save_preference(api, token, scenario["preference"])
        record["notes"].append("偏好已保存")
    if scenario.get("moments"):
        moment_state = ensure_moments(api, token, scenario["moments"])
        record["moments"] = moment_state
        record["notes"].append(f"动态 {moment_state.get('existing')} 条")

    member = api.data("GET", "/member/my", token=token)
    record["profile"] = member
    if member:
        record["profile_view"] = {
            field: member.get(field) for field in
            ("id", "nickname", "gender", "age", "rent_budget", "tidiness", "lease_term",
             "store_id", "store_name", "schedule_type", "has_pet", "smoking", "audit_status")
        }
    my = readiness_of(api, token)
    state = my.get("readiness") or {}
    record["readiness"] = {
        "can_run": state.get("can_run"),
        "blocker": state.get("blocker"),
        "checks": state.get("checks") or [],
        "limits": my.get("limits"),
    }
    blocker = state.get("blocker") or {}
    print(f"  readiness: can_run={state.get('can_run')} "
          f"checks={len(state.get('checks') or [])} "
          f"blocker={blocker.get('key') or '-'}")
    for check in state.get("checks") or []:
        print(f"    [{'OK' if check.get('ok') else 'NG'}] {check.get('key')}: {check.get('message')}")

    if scenario.get("probe_rerun") and not state.get("can_run"):
        body = api.call("POST", "/match/rerun", token=token)
        record["rerun_probe"] = {"code": body.get("code"), "msg": body.get("msg")}
        print(f"  直接调 /match/rerun -> {body.get('code')} {body.get('msg')}")
        record["notes"].append("已验证 API 层拒绝发起")

    if args.phase == "ready" or not scenario.get("run"):
        record["status"] = "未运行（只做前置检查）"
        return record

    if not state.get("can_run"):
        record["status"] = "未运行（readiness 阻断）"
        print("  跳过真实运行：readiness 已阻断")
        return record

    trials = args.trials or scenario.get("trials", 1)
    for index in range(1, trials + 1):
        trial = run_trial(api, admin, token, args.timeout, args.poll, index)
        record["runs"].append(trial)
        counts = trial.get("counts") or {}
        print(f"  trial {index}: {trial.get('run_status')} rounds={trial.get('total_round')} "
              f"cand={counts.get('total')} pass={counts.get('passed')} "
              f"rej={counts.get('rejected')} delivered={trial.get('delivered')} "
              f"wall={trial.get('wall_seconds')}s")
        hit = balance_hit(trial)
        if hit:
            record["status"] = f"中止：模型侧疑似余额/额度不足（命中「{hit}」）"
            record["balance_abort"] = True
            print("  !! 疑似 DeepSeek 余额/额度不足，停止后续场景")
            return record

    record["status"] = "已运行"
    return record


def summarize(record: dict) -> dict:
    runs = record.get("runs") or []
    if not runs:
        blocker = (record.get("readiness") or {}).get("blocker") or {}
        return {
            "runs": 0,
            "status": record.get("status"),
            "blocker": blocker.get("key"),
            "can_run": (record.get("readiness") or {}).get("can_run"),
        }
    walls = [row.get("wall_seconds") or 0 for row in runs]
    rounds = [row.get("total_round") or 0 for row in runs]
    delivered = [row.get("delivered") or 0 for row in runs]
    ok = [row for row in runs if row.get("run_status") == "已完成"]
    return {
        "runs": len(runs),
        "status": record.get("status"),
        "can_run": (record.get("readiness") or {}).get("can_run"),
        "completed": len(ok),
        "failed_runs": len(runs) - len(ok),
        "rounds": rounds,
        "delivered": delivered,
        "wall_seconds": walls,
        "wall_mean": round(sum(walls) / len(walls), 1),
    }


def write_outputs(records: list[dict], env: dict, args, stamp: str) -> Path:
    out_dir = REPORTS / f"scenario-matrix-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        (out_dir / f"{record['key'].lower()}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {
        "label": args.label or env.get("EVAL_LABEL"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "app_base": env.get("EVAL_APP_BASE"),
        "phase": args.phase,
        "scenarios": records,
        "summaries": {record["key"]: summarize(record) for record in records},
    }
    (out_dir / "matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# 场景矩阵原始结果 · {stamp}",
        "",
        f"- 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 应用：{env.get('EVAL_APP_BASE')}",
        f"- 阶段：{args.phase}",
        "",
        "| 场景 | 账号 | readiness | 运行 | 状态 | 轮次 | 候选 | 通过 | 否决 | 交付 | 耗时(s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for record in records:
        state = record.get("readiness") or {}
        blocker = state.get("blocker") or {}
        mark = "OK" if state.get("can_run") else f"阻断:{blocker.get('key')}"
        runs = record.get("runs") or []
        if runs:
            for row in runs:
                counts = row.get("counts") or {}
                lines.append(
                    f"| {record['key']} | {record['account']} | {mark} | #{row.get('trial')} | "
                    f"{row.get('run_status')} | {row.get('total_round')} | {counts.get('total')} | "
                    f"{counts.get('passed')} | {counts.get('rejected')} | {row.get('delivered')} | "
                    f"{row.get('wall_seconds')} |")
        else:
            lines.append(f"| {record['key']} | {record['account']} | {mark} | - | "
                         f"{record.get('status')} | - | - | - | - | - | - |")
    (out_dir / "matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="场景矩阵评测（真实多 Agent 匹配）")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--phase", choices=("ready", "run"), default="run")
    parser.add_argument("--only", help="只跑这些场景，逗号分隔，例如 S1,S3")
    parser.add_argument("--trials", type=int, help="覆盖每个场景的 trial 数")
    parser.add_argument("--poll", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=1300,
                        help="单次运行最长等待秒数（.env 里 MATCH_TIMEOUT_SECONDS=1200）")
    parser.add_argument("--label", help="报告标签")
    parser.add_argument("--stamp", help="输出目录时间戳")
    args = parser.parse_args(argv)

    env = load_env(args.env_file)
    api = Api(env.get("EVAL_APP_BASE", "http://127.0.0.1:8080"))
    admin = login(api, env.get("EVAL_ADMIN_USERNAME", "admin"),
                  env.get("EVAL_ADMIN_PASSWORD", "admin123"))
    selected = SCENARIOS
    if args.only:
        wanted = {item.strip().upper() for item in args.only.split(",") if item.strip()}
        selected = [item for item in SCENARIOS if item["key"].upper() in wanted]
        if not selected:
            raise SystemExit(f"没有匹配到场景：{args.only}")

    stamp = args.stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    records: list[dict] = []
    aborted = None
    for scenario in selected:
        try:
            record = run_scenario(api, admin, scenario, args, env)
        except Exception as exc:  # noqa: BLE001 单个场景失败不该拖垮整批
            record = {"key": scenario["key"], "title": scenario["title"],
                      "account": scenario["account"], "expect": scenario["expect"],
                      "why": scenario["why"], "fatal": f"{type(exc).__name__}: {exc}",
                      "status": "场景执行出错", "runs": []}
            print(f"  !! {record['fatal']}")
        records.append(record)
        if record.get("balance_abort"):
            aborted = record["key"]
            break

    out_dir = write_outputs(records, env, args, stamp)
    print(f"\n原始结果：{out_dir}")
    if aborted:
        print(f"!! 因 {aborted} 疑似余额不足提前停止")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
