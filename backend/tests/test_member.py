"""租客档案与生活照接口测试。

覆盖租客自己填写资料的校验、管理员审核的状态流转、启用停用，
以及两端各自能调哪些接口。

测试造出来的账号都带「单元测试专用」后缀，跑完由 conftest 的清扫夹具统一回收。
"""

from datetime import datetime, timedelta

import pytest

from common.times import LOCAL_TZ, now
from service import member_service

TEST_MARK = "单元测试专用"
PASSWORD = "123456"


def _new_member(client, admin_headers, tag):
    """造一个租客账号并登录，返回账号和它的请求头。"""
    username = f"hyzl{tag}{TEST_MARK}"
    assert client.post(
        "/user/add",
        json={"username": username, "name": f"租客{tag}{TEST_MARK}", "role": "USER"},
        headers=admin_headers,
    ).json()["code"] == "200"
    login = client.post("/login", json={"username": username, "password": PASSWORD}).json()
    assert login["code"] == "200"
    return username, login["data"]["token"]


def _payload(tag, **extra):
    """一份填得完整的资料，单条用例只改自己要验的那一项。"""
    data = {
        "nickname": f"昵称{tag}{TEST_MARK}",
        "gender": "女",
        "birth_date": "1996-05-20",
        "rent_budget": 3250,
        "tidiness": "一般",
        "occupation": "小学老师",
        "lease_term": "6-12个月",
        "store_id": 1,
        "schedule_type": "早睡早起",
        "has_pet": "无",
        "smoking": "不吸烟",
        "interest_tags": ["跑步"],
        "self_intro": f"平时喜欢跑步和看书，周末会去爬山。{tag}",
        "roommate_expectation": "希望找一个作息规律、愿意沟通的人。",
        "photo_paths": [],
    }
    data.update(extra)
    return data


def _save(client, token, tag, **extra):
    return client.post("/member/saveMy", json=_payload(tag, **extra), headers={"token": token}).json()


def _member_id_of(client, admin_headers, tag):
    """按昵称在管理端列表里反查租客档案的 id。"""
    page = client.get(
        "/member/selectPage",
        params={"nickname": f"{tag}{TEST_MARK}", "page_size": 100},
        headers=admin_headers,
    ).json()
    assert page["code"] == "200"
    for row in page["data"]["list"]:
        if row["nickname"] == f"昵称{tag}{TEST_MARK}":
            return row["id"]
    raise AssertionError(f"列表里没找到昵称带 {tag} 的租客档案")


def test_my_profile_is_empty_before_save(client, admin_headers):
    """还没填过资料时返回空值，页面据此提示去填写，而不是给一份空表单。"""
    _, token = _new_member(client, admin_headers, "kongbai")

    body = client.get("/member/my", headers={"token": token}).json()

    assert body["code"] == "200"
    assert body["data"] is None


def test_save_creates_profile_waiting_for_audit(client, admin_headers):
    """新提交的档案从待审核开始，年龄按出生日期现算，门店按编码拼出名字。"""
    _, token = _new_member(client, admin_headers, "xintijiao")

    body = _save(client, token, "xintijiao")

    assert body["code"] == "200"
    data = body["data"]
    assert data["audit_status"] == "待审核"
    assert data["audit_time"] is None
    assert data["store_name"] == "张江店"
    assert data["interest_tags"] == ["跑步"]
    assert data["photo_paths"] == []
    # 出生日期是上世纪九十年代的固定日期，年龄落在合理区间即可
    assert 25 <= data["age"] <= 35


def test_save_twice_keeps_one_profile(client, admin_headers):
    """一个账号只有一份资料，第二次保存是更新，不会多出一行。"""
    _, token = _new_member(client, admin_headers, "chongfubao")

    assert _save(client, token, "chongfubao")["code"] == "200"
    assert _save(client, token, "chongfubao", self_intro="第二次保存换了自我介绍的内容。")["code"] == "200"

    page = client.get(
        "/member/selectPage",
        params={"nickname": "chongfubao" + TEST_MARK, "page_size": 100},
        headers=admin_headers,
    ).json()
    assert len(page["data"]["list"]) == 1
    assert page["data"]["list"][0]["self_intro"] == "第二次保存换了自我介绍的内容。"


def test_save_without_nickname_is_rejected(client, admin_headers):
    """昵称是资料卡上展示的名字，留空直接拦下并说清要填哪个字段。"""
    _, token = _new_member(client, admin_headers, "wunickname")

    body = _save(client, token, "wunickname", nickname="")

    assert body["code"] == "500"
    assert body["msg"] == "请填写昵称"


def test_save_with_unreasonable_height_is_rejected(client, admin_headers):
    """预算超出正常范围基本是填错了，提示里写清可填的区间。"""
    _, token = _new_member(client, admin_headers, "shengao")

    body = _save(client, token, "shengao", rent_budget=30000)

    assert body["code"] == "500"
    assert body["msg"] == "月租预算请填 800 到 20000 之间的元数"


def test_save_with_unknown_interest_tag_is_rejected(client, admin_headers):
    """兴趣标签只认词表里的词，字典外的取值会让后面的画像和检索对不上。"""
    _, token = _new_member(client, admin_headers, "ziyoubiaoqian")

    body = _save(client, token, "ziyoubiaoqian", interest_tags=["自己编的标签"])

    assert body["code"] == "500"
    assert "不在可选清单里" in body["msg"]


def test_save_with_too_many_photos_is_rejected(client, admin_headers):
    """生活照有张数上限，超了要告诉用户最多能放几张。"""
    _, token = _new_member(client, admin_headers, "xiangcechaoshu")

    photos = [f"http://127.0.0.1:9090/files/download/zhaopian{i}.png" for i in range(10)]
    body = _save(client, token, "xiangcechaoshu", photo_paths=photos)

    assert body["code"] == "500"
    assert body["msg"] == "生活照最多放 9 张"


def test_admin_account_has_no_member_profile(client, admin_headers):
    """管理员账号不参与合租匹配，不能拿管理员账号填一份租客档案出来。"""
    body = client.get("/member/my", headers=admin_headers).json()

    assert body["code"] == "403"
    assert body["msg"] == "管理员账号不参与合租匹配，请用租客账号登录后再操作"


def test_member_cannot_read_member_list(client, admin_headers):
    """租客拿自己的 token 调管理端的租客列表会被拦下。"""
    _, token = _new_member(client, admin_headers, "yuequan")

    body = client.get("/member/selectPage", headers={"token": token}).json()

    assert body["code"] == "403"
    assert body["msg"] == "这个操作只有管理员能做，请换成管理员账号后再试"


def test_audit_pass_then_modify_goes_back_to_pending(client, admin_headers):
    """审核通过之后资料再被改动，会退回待审核，上一轮的结论不再沿用。"""
    _, token = _new_member(client, admin_headers, "shenheyitong")
    assert _save(client, token, "shenheyitong")["code"] == "200"
    member_id = _member_id_of(client, admin_headers, "shenheyitong")

    passed = client.post("/member/audit", json={
        "member_id": member_id, "audit_status": "已通过", "audit_remark": "资料完整"
    }, headers=admin_headers).json()
    assert passed["code"] == "200"

    detail = client.get("/member/my", headers={"token": token}).json()["data"]
    assert detail["audit_status"] == "已通过"
    assert detail["audit_time"] is not None

    again = _save(client, token, "shenheyitong", self_intro="审核通过之后又改了自我介绍。")
    assert again["data"]["audit_status"] == "待审核"
    assert again["data"]["audit_remark"] is None
    assert again["data"]["audit_time"] is None


def test_reject_requires_remark(client, admin_headers):
    """驳回必须写原因，租客要照着这条说明改资料。"""
    _, token = _new_member(client, admin_headers, "bohuiwubeizhu")
    assert _save(client, token, "bohuiwubeizhu")["code"] == "200"
    member_id = _member_id_of(client, admin_headers, "bohuiwubeizhu")

    body = client.post("/member/audit", json={
        "member_id": member_id, "audit_status": "已驳回", "audit_remark": "  "
    }, headers=admin_headers).json()

    assert body["code"] == "500"
    assert body["msg"] == "驳回时请填写原因，租客要照着这条说明修改档案"


def test_reject_remark_is_visible_to_member(client, admin_headers):
    """驳回原因写库之后，租客在自己的资料页能看到。"""
    _, token = _new_member(client, admin_headers, "bohuiyuanyin")
    assert _save(client, token, "bohuiyuanyin")["code"] == "200"
    member_id = _member_id_of(client, admin_headers, "bohuiyuanyin")

    assert client.post("/member/audit", json={
        "member_id": member_id, "audit_status": "已驳回", "audit_remark": "照片不清晰，请重新上传一张"
    }, headers=admin_headers).json()["code"] == "200"

    detail = client.get("/member/my", headers={"token": token}).json()["data"]
    assert detail["audit_status"] == "已驳回"
    assert detail["audit_remark"] == "照片不清晰，请重新上传一张"


def test_audit_result_must_be_pass_or_reject(client, admin_headers):
    """审核结论只能在通过与驳回之间选，绕过页面传别的值会被拦下。"""
    _, token = _new_member(client, admin_headers, "shenhejieguo")
    assert _save(client, token, "shenhejieguo")["code"] == "200"
    member_id = _member_id_of(client, admin_headers, "shenhejieguo")

    body = client.post("/member/audit", json={
        "member_id": member_id, "audit_status": "待审核"
    }, headers=admin_headers).json()

    assert body["code"] == "500"
    assert body["msg"] == "审核结论只能在 已通过、已驳回 里选"


def test_disable_and_enable_profile(client, admin_headers):
    """审核通过之后管理员仍然可以停用这份资料，改回来也能恢复。"""
    _, token = _new_member(client, admin_headers, "tingyonghuifu")
    assert _save(client, token, "tingyonghuifu")["code"] == "200"
    member_id = _member_id_of(client, admin_headers, "tingyonghuifu")
    assert client.post("/member/audit", json={
        "member_id": member_id, "audit_status": "已通过"
    }, headers=admin_headers).json()["code"] == "200"

    assert client.post("/member/updateEnabled", json={
        "member_id": member_id, "enabled": "否"
    }, headers=admin_headers).json()["code"] == "200"
    assert client.get("/member/my", headers={"token": token}).json()["data"]["enabled"] == "否"

    assert client.post("/member/updateEnabled", json={
        "member_id": member_id, "enabled": "是"
    }, headers=admin_headers).json()["code"] == "200"
    assert client.get("/member/my", headers={"token": token}).json()["data"]["enabled"] == "是"


def test_city_and_interest_tag_options_are_available(client, admin_headers):
    """门店清单和兴趣标签都从后端取，页面下拉框不用自己再维护一份。"""
    _, token = _new_member(client, admin_headers, "xuanxiang")
    headers = {"token": token}

    cities = client.get("/member/stores", headers=headers).json()
    assert cities["code"] == "200"
    assert len(cities["data"]) == 20
    assert {"id": 1, "name": "张江店", "area": "浦东"} in cities["data"]

    tags = client.get("/member/interestTags", headers=headers).json()
    assert tags["code"] == "200"
    assert tags["data"]
    assert {"name", "category"} <= set(tags["data"][0].keys())
    assert "运动" in {tag["category"] for tag in tags["data"]}


def test_select_page_filters_by_audit_status(client, admin_headers):
    """管理端能按审核状态筛，待审核的资料不会混进已通过的列表里。"""
    _, token = _new_member(client, admin_headers, "shaixuanshenhe")
    assert _save(client, token, "shaixuanshenhe")["code"] == "200"

    page = client.get(
        "/member/selectPage",
        params={"nickname": "shaixuanshenhe" + TEST_MARK, "audit_status": "已通过", "page_size": 100},
        headers=admin_headers,
    ).json()

    assert page["code"] == "200"
    assert page["data"]["list"] == []


def test_calc_age_returns_none_without_birth_date():
    """没填出生日期时不硬造一个年龄出来。"""
    assert member_service.calc_age(None) is None


def test_calc_age_counts_full_years():
    """年龄按生日算，还差一天没过生日就不算一岁。"""
    today = now()
    if (today.month, today.day) == (2, 29):
        pytest.skip("闰日不构造跨年日期")
    birth = datetime(today.year - 30, today.month, today.day, tzinfo=LOCAL_TZ)

    assert member_service.calc_age(birth) == 30
    assert member_service.calc_age(birth + timedelta(days=1)) == 29
