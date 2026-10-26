"""租客动态接口测试。

覆盖发布、修改、删除自己的动态，内容与配图数量校验，排序与分页，
以及别人的动态改不了删不掉、删动态时配图跟着清掉。

测试造出来的账号都带「单元测试专用」后缀，跑完由 conftest 的清扫夹具统一回收。
"""

import os

from service import file_service

TEST_MARK = "单元测试专用"
PASSWORD = "123456"


def _new_member(client, admin_headers, tag):
    """造一个租客账号并登录，返回账号和 token。这个账号还没有租客档案。"""
    username = f"dt{tag}{TEST_MARK}"
    assert client.post(
        "/user/add",
        json={"username": username, "name": f"动态{tag}{TEST_MARK}", "role": "USER"},
        headers=admin_headers,
    ).json()["code"] == "200"
    login = client.post("/login", json={"username": username, "password": PASSWORD}).json()
    assert login["code"] == "200"
    return username, login["data"]["token"]


def _with_profile(client, admin_headers, tag):
    """造一个租客账号并填好资料。动态挂在租客档案上，先有资料才能发。"""
    _, token = _new_member(client, admin_headers, tag)
    saved = client.post("/member/saveMy", json={
        "nickname": f"动态昵称{tag}{TEST_MARK}",
        "gender": "女",
        "birth_date": "1997-06-21",
        "rent_budget": 3150,
        "tidiness": "整洁",
        "occupation": "设计师",
        "lease_term": "6-12个月",
        "store_id": 4,
        "schedule_type": "早睡早起",
        "self_intro": f"平时做饭、养猫，周末常去看展。{tag}",
    }, headers={"token": token}).json()
    assert saved["code"] == "200"
    return token


def _publish(client, token, content=None, images=None, visible=None):
    payload = {"content": content if content is not None else f"今天在家烤了面包，第一次做成型。{TEST_MARK}"}
    if images is not None:
        payload["image_paths"] = images
    if visible is not None:
        payload["visible"] = visible
    return client.post("/moment/publish", json=payload, headers={"token": token}).json()


def _my_page(client, token, page_num=1, page_size=10):
    return client.get("/moment/selectMyPage", params={
        "page_num": page_num, "page_size": page_size}, headers={"token": token}).json()


def test_moment_requires_login(client):
    """没带 token 取我的动态会被拦回登录页。"""
    assert client.get("/moment/selectMyPage").json()["code"] == "401"


def test_admin_has_no_moment(client, admin_headers):
    """管理员账号不参与合租匹配，没有动态可发。"""
    body = client.get("/moment/selectMyPage", headers=admin_headers).json()

    assert body["code"] == "403"
    assert body["msg"] == "管理员账号不参与合租匹配，请用租客账号登录后再操作"


def test_publish_without_profile_is_rejected(client, admin_headers):
    """动态挂在租客档案上，还没填资料就发布要先把顺序说清楚。"""
    _, token = _new_member(client, admin_headers, "wuziliao")

    body = _publish(client, token)

    assert body["code"] == "500"
    assert body["msg"] == "请先填写并保存租客档案，再来发布动态"


def test_my_page_is_empty_before_publish(client, admin_headers):
    """还没发过动态时返回空列表，页面据此提示去写第一条。"""
    token = _with_profile(client, admin_headers, "kongbai")

    body = _my_page(client, token)

    assert body["code"] == "200"
    assert body["data"]["total"] == 0
    assert body["data"]["list"] == []


def test_publish_creates_moment(client, admin_headers):
    """发布成功后发布时间由服务端落，可见范围默认公开，没配图时是空数组。"""
    token = _with_profile(client, admin_headers, "fabu")

    body = _publish(client, token, content="周末去爬了香山，下山顺路吃了碗面。")

    assert body["code"] == "200"
    data = body["data"]
    assert data["content"] == "周末去爬了香山，下山顺路吃了碗面。"
    assert data["visible"] == "公开"
    assert data["image_paths"] == []
    assert data["publish_time"] is not None

    page = _my_page(client, token)
    assert page["data"]["total"] == 1
    assert page["data"]["list"][0]["content"] == "周末去爬了香山，下山顺路吃了碗面。"


def test_publish_without_content_is_rejected(client, admin_headers):
    """正文是画像唯一的材料，留空等于没发。"""
    token = _with_profile(client, admin_headers, "wuneirong")

    body = _publish(client, token, content="   ")

    assert body["code"] == "500"
    assert body["msg"] == "请填写动态内容"


def test_publish_with_too_long_content_is_rejected(client, admin_headers):
    """正文有字数上限，超了提示里写清上限是多少。"""
    token = _with_profile(client, admin_headers, "chaochang")

    body = _publish(client, token, content="很" * 501)

    assert body["code"] == "500"
    assert body["msg"] == "动态内容最多 500 个字"


def test_publish_with_too_many_images_is_rejected(client, admin_headers):
    """配图有张数上限。"""
    token = _with_profile(client, admin_headers, "peitu")
    images = [f"http://127.0.0.1:9090/files/download/dongtai{i}.png" for i in range(10)]

    body = _publish(client, token, images=images)

    assert body["code"] == "500"
    assert body["msg"] == "一条动态最多配 9 张图"


def test_publish_with_unknown_visible_is_rejected(client, admin_headers):
    """可见范围只有公开和仅匹配室友可见两档。"""
    token = _with_profile(client, admin_headers, "kefanwei")

    body = _publish(client, token, visible="所有人可见")

    assert body["code"] == "500"
    assert body["msg"] == "可见范围只能在 公开、仅匹配室友可见 里选"


def test_update_changes_content_and_keeps_publish_time(client, admin_headers):
    """改动态改的是正文和可见范围，发布时间不动。"""
    token = _with_profile(client, admin_headers, "xiugai")
    created = _publish(client, token, content="第一条动态的内容。")["data"]

    body = client.put("/moment/update", json={
        "content": "改过之后的动态内容。", "visible": "仅匹配室友可见", "image_paths": [],
    }, params={"moment_id": created["id"]}, headers={"token": token}).json()

    assert body["code"] == "200"
    assert body["data"]["content"] == "改过之后的动态内容。"
    assert body["data"]["visible"] == "仅匹配室友可见"
    assert body["data"]["publish_time"] == created["publish_time"]


def test_update_other_member_moment_is_rejected(client, admin_headers):
    """拿别人的动态编号来改，查不到这一条。"""
    owner_token = _with_profile(client, admin_headers, "yongyou")
    other_token = _with_profile(client, admin_headers, "bieren")
    created = _publish(client, owner_token)["data"]

    body = client.put("/moment/update", json={"content": "改成别人的内容。"},
                      params={"moment_id": created["id"]}, headers={"token": other_token}).json()

    assert body["code"] == "500"
    assert body["msg"] == "未找到这条动态，请刷新列表后重试"
    # 原来那条没被动过
    page = _my_page(client, owner_token)
    assert page["data"]["list"][0]["content"] == created["content"]


def test_delete_own_moment(client, admin_headers):
    """可以删掉自己的动态，删完列表里就没有了。"""
    token = _with_profile(client, admin_headers, "shanziji")
    created = _publish(client, token)["data"]

    body = client.delete(
        "/moment/delete/" + str(created["id"]), headers={"token": token}).json()

    assert body["code"] == "200"
    assert _my_page(client, token)["data"]["total"] == 0


def test_delete_other_member_moment_is_rejected(client, admin_headers):
    """别人的动态删不掉。"""
    owner_token = _with_profile(client, admin_headers, "zhuren")
    other_token = _with_profile(client, admin_headers, "luren")
    created = _publish(client, owner_token)["data"]

    body = client.delete(
        "/moment/delete/" + str(created["id"]), headers={"token": other_token}).json()

    assert body["code"] == "500"
    assert body["msg"] == "未找到这条动态，请刷新列表后重试"
    assert _my_page(client, owner_token)["data"]["total"] == 1


def test_my_page_is_ordered_by_publish_time_desc(client, admin_headers):
    """列表按发布时间倒序，后发的排在最前面。"""
    token = _with_profile(client, admin_headers, "paixu")
    assert _publish(client, token, content="第一条")["code"] == "200"
    assert _publish(client, token, content="第二条")["code"] == "200"
    assert _publish(client, token, content="第三条")["code"] == "200"

    page = _my_page(client, token)

    assert page["data"]["total"] == 3
    assert [row["content"] for row in page["data"]["list"]] == ["第三条", "第二条", "第一条"]


def test_my_page_pages(client, admin_headers):
    """动态条数多了要翻页，每页的条数按传进来的 page_size 走。"""
    token = _with_profile(client, admin_headers, "fanye")
    for index in range(3):
        assert _publish(client, token, content=f"第 {index + 1} 条动态")["code"] == "200"

    first = _my_page(client, token, page_num=1, page_size=2)
    second = _my_page(client, token, page_num=2, page_size=2)

    assert first["data"]["total"] == 3
    assert len(first["data"]["list"]) == 2
    assert len(second["data"]["list"]) == 1


def test_delete_moment_removes_images_from_disk(client, admin_headers):
    """动态删了之后配图没人再引用，磁盘上的文件要跟着清掉。"""
    token = _with_profile(client, admin_headers, "qingtu")
    filename = f"dongtaipeitu{TEST_MARK}.png"
    os.makedirs(file_service.UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(file_service.UPLOAD_DIR, filename)
    with open(file_path, "wb") as handle:
        handle.write(b"test")
    created = _publish(
        client, token, images=[file_service.DOWNLOAD_PREFIX + filename])["data"]
    assert os.path.exists(file_path)

    body = client.delete(
        "/moment/delete/" + str(created["id"]), headers={"token": token}).json()

    assert body["code"] == "200"
    assert not os.path.exists(file_path)


def test_visible_options_are_available(client, admin_headers):
    """可见范围的取值从后端取，页面不自己维护一份。"""
    token = _with_profile(client, admin_headers, "kefanweixuanxiang")

    body = client.get("/moment/visibleOptions", headers={"token": token}).json()

    assert body["code"] == "200"
    assert body["data"] == ["公开", "仅匹配室友可见"]
