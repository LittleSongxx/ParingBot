"""兴趣标签词表接口测试。

覆盖标签的增删改查、类目与取值的校验、被租客档案引用时的删除与改名拦截，
以及停用标签对租客档案的影响。

测试造出来的标签和账号都带「单元测试专用」后缀，跑完由 conftest 的清扫夹具统一回收。
"""

from service import interest_tag_service

TEST_MARK = "单元测试专用"
PASSWORD = "123456"


def _add(client, admin_headers, tag_name, category="运动", **extra):
    return client.post("/interestTag/add", json={
        "tag_name": tag_name, "category": category, **extra}, headers=admin_headers).json()


def _row_of(client, admin_headers, tag_name) -> dict:
    """按标签名在管理端列表里查出这一行。"""
    page = client.get("/interestTag/selectPage", params={
        "tag_name": tag_name, "page_size": 100}, headers=admin_headers).json()
    assert page["code"] == "200"
    for row in page["data"]["list"]:
        if row["tag_name"] == tag_name:
            return row
    raise AssertionError(f"列表里没找到标签 {tag_name}")


def _id_of(client, admin_headers, tag_name) -> int:
    return _row_of(client, admin_headers, tag_name)["id"]


def _new_member(client, admin_headers, tag):
    """造一个租客账号并登录，返回账号和 token。这个账号还没有租客档案。"""
    username = f"bq{tag}{TEST_MARK}"
    assert client.post(
        "/user/add",
        json={"username": username, "name": f"标签{tag}{TEST_MARK}", "role": "USER"},
        headers=admin_headers,
    ).json()["code"] == "200"
    login = client.post("/login", json={"username": username, "password": PASSWORD}).json()
    assert login["code"] == "200"
    return username, login["data"]["token"]


def _profile_payload(tag, tags):
    return {
        "nickname": f"标签昵称{tag}{TEST_MARK}",
        "gender": "男",
        "birth_date": "1993-11-08",
        "rent_budget": 3800,
        "tidiness": "一般",
        "occupation": "产品经理",
        "lease_term": "1-2年",
        "store_id": 2,
        "schedule_type": "早睡早起",
        "interest_tags": tags,
        "self_intro": f"喜欢跑步和看展，周末常去咖啡馆。{tag}",
    }


def _save_profile(client, token, tag, tags):
    return client.post("/member/saveMy", json=_profile_payload(tag, tags),
                       headers={"token": token}).json()


def _with_profile(client, admin_headers, tag, tags):
    """造一个租客账号并填好资料，资料里的兴趣标签用传进来的这几个。"""
    _, token = _new_member(client, admin_headers, tag)
    saved = _save_profile(client, token, tag, tags)
    assert saved["code"] == "200"
    return token


def test_tag_page_requires_admin(client, admin_headers):
    """词表维护是管理员的活，租客和没登录的访问都要被拦下。"""
    assert client.get("/interestTag/selectPage").json()["code"] == "401"

    _, token = _new_member(client, admin_headers, "yuequan")
    body = client.get("/interestTag/selectPage", headers={"token": token}).json()

    assert body["code"] == "403"
    assert body["msg"] == "这个操作只有管理员能做，请换成管理员账号后再试"


def test_add_creates_tag(client, admin_headers):
    """新增的标签默认启用、排序号不填按 0 处理，还没有租客用过它。"""
    tag_name = f"标签xinzeng{TEST_MARK}"

    body = _add(client, admin_headers, tag_name)

    assert body["code"] == "200"
    row = _row_of(client, admin_headers, tag_name)
    assert row["category"] == "运动"
    assert row["enabled"] == "是"
    assert row["sort"] == 0
    assert row["used_count"] == 0


def test_add_duplicate_name_is_rejected(client, admin_headers):
    """词表里标签名唯一，重复新增要指回已有的那一条。"""
    tag_name = f"标签chongfu{TEST_MARK}"
    assert _add(client, admin_headers, tag_name)["code"] == "200"

    body = _add(client, admin_headers, tag_name)

    assert body["code"] == "500"
    assert body["msg"] == f"标签「{tag_name}」已经在词表里了，直接改那一条就行"


def test_add_without_name_is_rejected(client, admin_headers):
    """标签名不能留空。"""
    body = _add(client, admin_headers, "")

    assert body["code"] == "500"
    assert body["msg"] == "请填写标签名"


def test_add_with_unknown_category_is_rejected(client, admin_headers):
    """类目只在八个里选，页面下拉框和这里用的是同一份清单。"""
    body = _add(client, admin_headers, f"标签leimu{TEST_MARK}", category="美食天地")

    assert body["code"] == "500"
    assert body["msg"] == "标签类目只能在 运动、影音、美食、旅行、宠物、阅读、游戏、艺术 里选"


def test_add_with_bad_sort_is_rejected(client, admin_headers):
    """排序号是一个有限的整数范围，超出去基本是填错了。"""
    body = _add(client, admin_headers, f"标签paixu{TEST_MARK}", sort=1000)

    assert body["code"] == "500"
    assert body["msg"] == "排序号请填 0 到 999 之间的整数"


def test_add_with_bad_enabled_is_rejected(client, admin_headers):
    """启用状态只有是和非两档。"""
    body = _add(client, admin_headers, f"标签zhuangtai{TEST_MARK}", enabled="停")

    assert body["code"] == "500"
    assert body["msg"] == "启用状态只能是是或否"


def test_select_page_filters_by_category_and_status(client, admin_headers):
    """类目和启用状态都能筛，字典大了之后靠这两个条件找词。"""
    pinyin = f"标签shaixuan{TEST_MARK}"
    assert _add(client, admin_headers, pinyin, category="阅读")["code"] == "200"
    assert _add(client, admin_headers, f"{pinyin}停用", category="阅读", enabled="否")["code"] == "200"

    page = client.get("/interestTag/selectPage", params={
        "tag_name": pinyin, "category": "阅读", "enabled": "是", "page_size": 100,
    }, headers=admin_headers).json()

    assert page["code"] == "200"
    assert [row["tag_name"] for row in page["data"]["list"]] == [pinyin]


def test_update_renames_unused_tag(client, admin_headers):
    """没人用过的标签可以改名换类目。"""
    old_name = f"标签jiu{TEST_MARK}"
    new_name = f"标签xin{TEST_MARK}"
    assert _add(client, admin_headers, old_name, category="运动")["code"] == "200"

    body = client.put("/interestTag/update", json={
        "id": _id_of(client, admin_headers, old_name),
        "tag_name": new_name, "category": "艺术", "enabled": "是", "sort": 5,
    }, headers=admin_headers).json()

    assert body["code"] == "200"
    row = _row_of(client, admin_headers, new_name)
    assert row["category"] == "艺术"
    assert row["sort"] == 5


def test_update_to_duplicate_name_is_rejected(client, admin_headers):
    """改名不能和词表里已有的标签撞名。"""
    first = f"标签yi{TEST_MARK}"
    second = f"标签er{TEST_MARK}"
    assert _add(client, admin_headers, first)["code"] == "200"
    assert _add(client, admin_headers, second)["code"] == "200"

    body = client.put("/interestTag/update", json={
        "id": _id_of(client, admin_headers, second),
        "tag_name": first, "category": "运动",
    }, headers=admin_headers).json()

    assert body["code"] == "500"
    assert body["msg"] == f"标签「{first}」已经在词表里了"


def test_update_name_of_used_tag_is_rejected(client, admin_headers):
    """已经有租客在用的标签不许改名，改了之后租客档案里的词就对不上词表了。"""
    tag_name = f"标签yongzhe{TEST_MARK}"
    assert _add(client, admin_headers, tag_name, category="旅行")["code"] == "200"
    _with_profile(client, admin_headers, "gaibiaoqian", [tag_name])

    body = client.put("/interestTag/update", json={
        "id": _id_of(client, admin_headers, tag_name),
        "tag_name": f"标签gaiming{TEST_MARK}", "category": "旅行",
    }, headers=admin_headers).json()

    assert body["code"] == "500"
    assert "改名或换类目会让他们的标签对不上词表" in body["msg"]


def test_update_sort_of_used_tag_is_allowed(client, admin_headers):
    """排序号改了不影响取值，有人在用也允许改。"""
    tag_name = f"标签paixukeyi{TEST_MARK}"
    assert _add(client, admin_headers, tag_name, category="宠物")["code"] == "200"
    _with_profile(client, admin_headers, "paixu", [tag_name])

    body = client.put("/interestTag/update", json={
        "id": _id_of(client, admin_headers, tag_name),
        "tag_name": tag_name, "category": "宠物", "sort": 3,
    }, headers=admin_headers).json()

    assert body["code"] == "200"
    assert _row_of(client, admin_headers, tag_name)["sort"] == 3


def test_delete_unused_tag(client, admin_headers):
    """没人用过的标签可以直接删掉。"""
    tag_name = f"标签shandiao{TEST_MARK}"
    assert _add(client, admin_headers, tag_name)["code"] == "200"

    body = client.delete(
        "/interestTag/delete/" + str(_id_of(client, admin_headers, tag_name)),
        headers=admin_headers).json()

    assert body["code"] == "200"
    page = client.get("/interestTag/selectPage", params={
        "tag_name": tag_name, "page_size": 100}, headers=admin_headers).json()
    assert page["data"]["list"] == []


def test_delete_used_tag_is_rejected(client, admin_headers):
    """被租客档案引用的标签删不掉，提示里要给出停用这条替代做法。"""
    tag_name = f"标签bunengshan{TEST_MARK}"
    assert _add(client, admin_headers, tag_name, category="游戏")["code"] == "200"
    _with_profile(client, admin_headers, "bunengshan", [tag_name])

    body = client.delete(
        "/interestTag/delete/" + str(_id_of(client, admin_headers, tag_name)),
        headers=admin_headers).json()

    assert body["code"] == "500"
    assert "请改为停用" in body["msg"]
    assert _row_of(client, admin_headers, tag_name)["used_count"] == 1


def test_delete_batch_checks_the_whole_selection_first(client, admin_headers):
    """批量删除里只要有一个删不掉，整批都不动。"""
    keeper = f"标签keyishan{TEST_MARK}"
    blocked = f"标签beidangzhu{TEST_MARK}"
    assert _add(client, admin_headers, keeper, category="影音")["code"] == "200"
    assert _add(client, admin_headers, blocked, category="影音")["code"] == "200"
    _with_profile(client, admin_headers, "piliang", [blocked])
    ids = [_id_of(client, admin_headers, keeper), _id_of(client, admin_headers, blocked)]

    body = client.request("DELETE", "/interestTag/deleteBatch", json=ids,
                          headers=admin_headers).json()

    assert body["code"] == "500"
    # 整批都没删：可删的那个也还在
    assert _row_of(client, admin_headers, keeper)["tag_name"] == keeper
    assert _row_of(client, admin_headers, blocked)["tag_name"] == blocked


def test_delete_unknown_tag_is_rejected(client, admin_headers):
    """记录不存在时给人话提示，而不是报一个数据库错误。"""
    body = client.delete("/interestTag/delete/99999999", headers=admin_headers).json()

    assert body["code"] == "500"
    assert body["msg"] == "未找到这个标签，请刷新列表后重试"


def test_update_enabled_with_bad_value_is_rejected(client, admin_headers):
    """停用启用接口同样只认是和非。"""
    tag_name = f"标签zhuangtaibad{TEST_MARK}"
    assert _add(client, admin_headers, tag_name)["code"] == "200"

    body = client.post("/interestTag/updateEnabled", json={
        "tag_id": _id_of(client, admin_headers, tag_name), "enabled": "停止",
    }, headers=admin_headers).json()

    assert body["code"] == "500"
    assert body["msg"] == "启用状态只能是是或否"


def test_disabled_tag_disappears_from_member_options(client, admin_headers):
    """停用之后，租客填资料时的下拉框里不再有这个标签。"""
    tag_name = f"标签buxianshi{TEST_MARK}"
    assert _add(client, admin_headers, tag_name, category="美食")["code"] == "200"
    token = _with_profile(client, admin_headers, "buxianshi", [tag_name])

    assert client.post("/interestTag/updateEnabled", json={
        "tag_id": _id_of(client, admin_headers, tag_name), "enabled": "否",
    }, headers=admin_headers).json()["code"] == "200"

    options = client.get("/member/interestTags", headers={"token": token}).json()
    assert tag_name not in [item["name"] for item in options["data"]]


def test_member_keeps_disabled_tag_when_saving_profile_again(client, admin_headers):
    """已经选好的标签不会因为管理员把它停用就保存不了。"""
    tag_name = f"标签liuzhe{TEST_MARK}"
    assert _add(client, admin_headers, tag_name, category="阅读")["code"] == "200"
    token = _with_profile(client, admin_headers, "liuzhe", [tag_name])
    assert client.post("/interestTag/updateEnabled", json={
        "tag_id": _id_of(client, admin_headers, tag_name), "enabled": "否",
    }, headers=admin_headers).json()["code"] == "200"

    again = _save_profile(client, token, "liuzhe", [tag_name])

    assert again["code"] == "200"
    assert again["data"]["interest_tags"] == [tag_name]


def test_other_member_cannot_pick_a_disabled_tag(client, admin_headers):
    """别的租客想新选这个停用标签时会被拦下，停用才对所有人成立。"""
    tag_name = f"标签bierenbuneng{TEST_MARK}"
    assert _add(client, admin_headers, tag_name, category="美食")["code"] == "200"
    _with_profile(client, admin_headers, "xuanbule", [tag_name])
    assert client.post("/interestTag/updateEnabled", json={
        "tag_id": _id_of(client, admin_headers, tag_name), "enabled": "否",
    }, headers=admin_headers).json()["code"] == "200"
    _, other_token = _new_member(client, admin_headers, "bieren")

    body = _save_profile(client, other_token, "bieren", [tag_name])

    assert body["code"] == "500"
    assert "不在可选清单里" in body["msg"]


async def test_used_count_ignores_prefix_matches(db):
    """使用人数的统计口径：把逗号分隔的那一列拆开按整段比对。

    两个标签名互为前缀时（比如「标签短」和「标签短延长」），用 LIKE 查会互相
    误伤，所以先用 LIKE 收窄、再从内存里精确比对，数出来的才是真正在用的人数。
    """
    from models import InterestTag, MemberProfile, User

    short = f"标签jishu{TEST_MARK}"
    longer = short + "延长"
    await InterestTag.create(tag_name=short, category="运动")
    await InterestTag.create(tag_name=longer, category="运动")
    user = await User.create(
        username=f"bqjishu{TEST_MARK}", password="x", name=f"计数{TEST_MARK}", role="USER")
    await MemberProfile.create(
        user_id=user.id, nickname=f"计数昵称{TEST_MARK}", gender="女", interest_tags=longer)

    page = await interest_tag_service.select_page(tag_name=f"标签jishu{TEST_MARK}", page_size=100)

    counts = {row["tag_name"]: row["used_count"] for row in page.list}
    assert counts[short] == 0
    assert counts[longer] == 1
