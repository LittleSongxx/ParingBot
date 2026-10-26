"""合住偏好接口测试。

覆盖七个维度的取值校验、「必须 / 加分」标注的数量约束、可放宽维度的判断，
以及两端各自能调哪些接口。

测试造出来的账号都带「单元测试专用」后缀，跑完由 conftest 的清扫夹具统一回收。
"""

import pytest

from models import RoommatePreference
from service import preference_service

TEST_MARK = "单元测试专用"
PASSWORD = "123456"


def _new_member(client, admin_headers, tag):
    """造一个租客账号并登录，返回账号和 token。这个账号还没有租客档案。"""
    username = f"ph{tag}{TEST_MARK}"
    assert client.post(
        "/user/add",
        json={"username": username, "name": f"偏好{tag}{TEST_MARK}", "role": "USER"},
        headers=admin_headers,
    ).json()["code"] == "200"
    login = client.post("/login", json={"username": username, "password": PASSWORD}).json()
    assert login["code"] == "200"
    return username, login["data"]["token"]


def _with_profile(client, admin_headers, tag):
    """造一个租客账号并填好资料。合住偏好挂在租客档案上，先有资料才能设置。"""
    username, token = _new_member(client, admin_headers, tag)
    saved = client.post("/member/saveMy", json={
        "nickname": f"偏好昵称{tag}{TEST_MARK}",
        "gender": "女",
        "birth_date": "1995-03-12",
        "rent_budget": 3400,
        "tidiness": "一般",
        "occupation": "会计",
        "lease_term": "6-12个月",
        "store_id": 5,
        "schedule_type": "早睡早起",
        "self_intro": f"平时看电影、练瑜伽，周末喜欢做饭。{tag}",
    }, headers={"token": token}).json()
    assert saved["code"] == "200"
    return username, token


def _payload(**extra):
    """一份填得合规的偏好：必须 3 项、加分 4 项，单条用例只改自己要验的那一项。"""
    data = {
        "age_min": 26,
        "age_max": 34,
        "age_required": "加分",
        "budget_min": 3250,
        "budget_max": 4250,
        "budget_required": "必须",
        "tidiness_min": "一般",
        "tidiness_required": "加分",
        "store_scope": "同片区",
        "store_required": "必须",
        "schedule_accept": ["早睡早起"],
        "schedule_required": "加分",
        "lease_min": "6-12个月",
        "lease_required": "加分",
        "pet_accept": "接受",
        "pet_required": "必须",
    }
    data.update(extra)
    return data


def _save(client, token, **extra):
    return client.post("/preference/saveMy", json=_payload(**extra),
                       headers={"token": token}).json()


def _draft(**extra) -> RoommatePreference:
    """一份没落库的偏好对象，单测可放宽维度的纯函数时用，不用连数据库。"""
    values = {
        "member_id": 0,
        "age_min": None, "age_max": None, "age_required": "加分",
        "budget_min": None, "budget_max": None, "budget_required": "加分",
        "tidiness_min": None, "tidiness_required": "加分",
        "store_scope": "不限", "store_required": "加分",
        "schedule_accept": None, "schedule_required": "加分",
        "lease_min": None, "lease_required": "加分",
        "pet_accept": None, "pet_required": "加分",
    }
    values.update(extra)
    return RoommatePreference(**values)


def test_preference_requires_login(client):
    """没带 token 取我的偏好会被拦回登录页。"""
    body = client.get("/preference/my").json()

    assert body["code"] == "401"


def test_admin_has_no_preference(client, admin_headers):
    """管理员账号不参与合租匹配，没有合住偏好可设置。"""
    body = client.get("/preference/my", headers=admin_headers).json()

    assert body["code"] == "403"
    assert body["msg"] == "管理员账号不参与合租匹配，请用租客账号登录后再操作"


def test_save_without_profile_is_rejected(client, admin_headers):
    """偏好挂在租客档案上，还没填资料就保存要先把顺序说清楚。"""
    _, token = _new_member(client, admin_headers, "wuziliao")

    body = _save(client, token)

    assert body["code"] == "500"
    assert body["msg"] == "请先填写并保存租客档案，再来设置合住偏好"


def test_my_preference_is_empty_before_save(client, admin_headers):
    """还没设置过偏好时返回空值，页面据此提示去填写。"""
    _, token = _with_profile(client, admin_headers, "kongbai")

    body = client.get("/preference/my", headers={"token": token}).json()

    assert body["code"] == "200"
    assert body["data"] is None


def test_save_keeps_dimensions_and_split_schedule(client, admin_headers):
    """保存成功后七个维度都在，作息拆成数组，两份派生清单跟着一起返回。"""
    _, token = _with_profile(client, admin_headers, "baocun")

    body = _save(client, token)

    assert body["code"] == "200"
    data = body["data"]
    assert data["age_min"] == 26
    assert data["age_max"] == 34
    assert data["schedule_accept"] == ["早睡早起"]
    assert data["store_scope"] == "同片区"
    assert [one["name"] for one in data["must_dimensions"]] == ["预算", "门店", "宠物态度"]
    # 只有标了「加分」而且确实有约束的维度才可能被放宽
    assert [one["code"] for one in data["relaxable_dimensions"]] == ["age", "tidiness", "schedule", "lease"]


def test_save_twice_updates_the_same_preference(client, admin_headers):
    """一个租客只有一条偏好，第二次保存是更新，返回的还是同一条记录。"""
    _, token = _with_profile(client, admin_headers, "chongfubao")

    first = _save(client, token)["data"]
    second = _save(client, token, age_max=36)["data"]

    assert second["id"] == first["id"]
    assert second["age_max"] == 36


def test_save_with_reversed_age_range_is_rejected(client, admin_headers):
    """年龄下限大于上限属于填错了，提示直接说清是哪一头反了。"""
    _, token = _with_profile(client, admin_headers, "nianlingfan")

    body = _save(client, token, age_min=40, age_max=30)

    assert body["code"] == "500"
    assert body["msg"] == "年龄的下限不能大于上限"


def test_save_with_out_of_range_age_is_rejected(client, admin_headers):
    """年龄区间要在正常范围里，超出范围基本是选错了。"""
    _, token = _with_profile(client, admin_headers, "nianlingchaochu")

    body = _save(client, token, age_min=10, age_max=30)

    assert body["code"] == "500"
    assert body["msg"] == "年龄范围请填 18 到 80 之间"


def test_save_with_reversed_budget_range_is_rejected(client, admin_headers):
    """预算的上下限同样要按顺序填。"""
    _, token = _with_profile(client, admin_headers, "shengaofan")

    body = _save(client, token, budget_min=4500, budget_max=3500)

    assert body["code"] == "500"
    assert body["msg"] == "预算的下限不能大于上限"


def test_save_with_unknown_tidiness_is_rejected(client, admin_headers):
    """最低整洁度只认四档加「不限」，字典外的取值不落库。"""
    _, token = _with_profile(client, admin_headers, "xuelibuzhi")

    body = _save(client, token, tidiness_min="中专")

    assert body["code"] == "500"
    assert body["msg"] == "最低整洁度只能在 随意、一般、整洁、洁癖、不限 里选"


def test_save_without_schedule_is_rejected(client, admin_headers):
    """作息是多选，一个都不选就没有判断依据。"""
    _, token = _with_profile(client, admin_headers, "hunshiweixuan")

    body = _save(client, token, schedule_accept=[])

    assert body["code"] == "500"
    assert body["msg"] == "请至少选一个可以接受的作息"


def test_save_with_unknown_required_flag_is_rejected(client, admin_headers):
    """标注只有必须和加分两种，写别的值筛选官不知道能不能放宽。"""
    _, token = _with_profile(client, admin_headers, "biaozhubuzhi")

    body = _save(client, token, age_required="很重要")

    assert body["code"] == "500"
    assert body["msg"] == "年龄要选「必须」或「加分」"


def test_save_with_too_few_must_dimensions_is_rejected(client, admin_headers):
    """一个必须项都不填等于没有硬性条件，提示里要报出当前数量。"""
    _, token = _with_profile(client, admin_headers, "bixujiaoshao")
    only_bonus = {
        "age_required": "加分", "budget_required": "加分", "tidiness_required": "加分",
        "store_required": "加分", "schedule_required": "加分", "lease_required": "加分",
        "pet_required": "加分",
    }

    body = _save(client, token, **only_bonus)

    assert body["code"] == "500"
    assert "要在 2 到 4 个之间，现在有 0 个" in body["msg"]


def test_save_with_too_many_must_dimensions_is_rejected(client, admin_headers):
    """必须项超过上限就轮到筛选官无路可走了，这一步要拦住。"""
    _, token = _with_profile(client, admin_headers, "bixujiaoduo")
    almost_all_must = {
        "age_required": "必须", "budget_required": "必须", "tidiness_required": "必须",
        "store_required": "必须", "schedule_required": "必须", "pet_required": "加分",
    }

    body = _save(client, token, **almost_all_must)

    assert body["code"] == "500"
    assert "要在 2 到 4 个之间，现在有 5 个" in body["msg"]


def test_no_limit_value_is_not_relaxable(client, admin_headers):
    """「不限」「无所谓」对谁都成立，放宽它们等于没放宽，不算进可放宽维度。"""
    _, token = _with_profile(client, admin_headers, "buxian")

    body = _save(client, token, store_scope="不限", tidiness_min="不限", pet_accept="无所谓")

    data = body["data"]
    assert data["store_scope"] == "不限"
    # 整洁度和租期选「不限」时存空值，页面回填时才认得出是不设门槛
    assert data["tidiness_min"] is None
    assert [one["code"] for one in data["relaxable_dimensions"]] == ["age", "schedule", "lease"]


def test_full_schedule_accept_is_not_relaxable(client, admin_headers):
    """三档作息全选等于不限制，这一项也不该占用放宽名额。"""
    _, token = _with_profile(client, admin_headers, "hunshiquanxuan")

    body = _save(client, token, schedule_accept=["早睡早起", "正常作息", "夜猫子"])

    assert body["data"]["schedule_accept"] == ["早睡早起", "正常作息", "夜猫子"]
    assert "schedule" not in [one["code"] for one in body["data"]["relaxable_dimensions"]]


def test_lowest_lease_is_not_relaxable(client, admin_headers):
    """最低租期档已经是最宽的一档，选了它就等于不设下限。"""
    _, token = _with_profile(client, admin_headers, "shouruzuidi")

    body = _save(client, token, lease_min="3个月以下")

    assert "lease" not in [one["code"] for one in body["data"]["relaxable_dimensions"]]


def test_options_lists_every_dimension_choice(client, admin_headers):
    """取值清单和必须项区间都由后端给出，页面不用自己维护一份。"""
    _, token = _with_profile(client, admin_headers, "xuanxiang")

    body = client.get("/preference/options", headers={"token": token}).json()

    assert body["code"] == "200"
    data = body["data"]
    assert data["tidiness_levels"] == ["随意", "一般", "整洁", "洁癖"]
    assert data["store_scopes"] == ["同门店", "同片区", "不限"]
    assert data["pet_accepts"] == ["接受", "不接受", "无所谓"]
    assert data["must_count_range"] == {"min": 2, "max": 4}
    assert data["age_range"] == {"min": 18, "max": 80}
    assert data["budget_range"] == {"min": 800, "max": 20000}
    assert data["dimension_count"] == 7


def test_has_constraint_recognizes_real_requirements():
    """七个维度的「有没有实际约束」逐个确认一遍。"""
    draft = _draft(
        age_min=25, age_max=32, tidiness_min="一般", store_scope="同门店",
        schedule_accept="早睡早起", lease_min="6-12个月", pet_accept="不接受")

    assert preference_service.has_constraint(draft, "age") is True
    assert preference_service.has_constraint(draft, "tidiness") is True
    assert preference_service.has_constraint(draft, "store") is True
    assert preference_service.has_constraint(draft, "schedule") is True
    assert preference_service.has_constraint(draft, "lease") is True
    assert preference_service.has_constraint(draft, "pet") is True
    # 「接受」不排除任何人，不算实际约束
    assert preference_service.has_constraint(_draft(pet_accept="接受"), "pet") is False
    # 预算上下限都没填，这一项对谁都成立
    assert preference_service.has_constraint(draft, "budget") is False


def test_has_constraint_rejects_unknown_dimension():
    """维度编码写错时直接报错，不能悄悄当成「可以放宽」。"""
    with pytest.raises(ValueError):
        preference_service.has_constraint(_draft(), "weight")


def test_relaxable_dimensions_skip_must_and_no_limit():
    """可放宽清单同时排除两类维度：标了必须的、取值本身不限制任何人的。"""
    draft = _draft(
        age_min=25, age_max=32, age_required="必须",
        tidiness_min="一般", tidiness_required="加分",
        store_scope="不限", store_required="加分",
        schedule_accept="早睡早起,正常作息", schedule_required="加分",
        lease_min="3个月以下", lease_required="加分",
        pet_accept="接受", pet_required="必须")

    assert [one["code"] for one in preference_service.relaxable_dimensions(draft)] == [
        "tidiness", "schedule"]
