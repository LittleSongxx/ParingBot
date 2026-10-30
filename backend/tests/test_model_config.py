"""AI 模型配置接口测试。

覆盖配置列表、用途校验、密钥脱敏、一个用途只留一条启用配置、
删除拦截和连通性测试的失败路径。

连通性测试要真实调模型接口，需要有效的 API Key，这里只覆盖没填密钥时的失败路径：
那一步在发起调用之前就返回了，不会产生任何网络请求。填了密钥之后的成功路径在页面上手工验证。

测试会临时顶掉初始化数据里「画像」用途那条配置的启用状态，用例里用 try/finally 恢复回去，
test_seed_configs_cover_four_purposes 盯住这件事：一旦上一次跑测留下了脏状态，它会直接报出来。
"""

import pytest

from ai import model_factory
from common.exception_handler import CustomException
from models import AiModelConfig
from service import model_config_service

TEST_MARK = "单元测试专用"
# 初始化数据里四个用途各有一条启用中的配置，一个用途对应一个 Agent 角色
SEED_PURPOSES = ("调度", "画像", "筛选", "审核")
# 初始化数据里「画像」用途那条配置，测试顶掉它之后要恢复
SEED_PORTRAIT_NAME = "画像提取模型"


def _list_configs(client, admin_headers, **params) -> list:
    body = client.get("/aiModelConfig/selectPage", params={"page_size": 100, **params},
                      headers=admin_headers).json()
    assert body["code"] == "200"
    return body["data"]["list"]


def _row_of(client, admin_headers, name) -> dict:
    for row in _list_configs(client, admin_headers, name=name):
        if row["name"] == name:
            return row
    raise AssertionError(f"列表里没找到配置 {name}")


def _add(client, admin_headers, **fields) -> dict:
    payload = {
        "name": f"测试配置{TEST_MARK}",
        "model_purpose": "画像",
        "provider": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-chat",
        "enabled": "否",
    }
    payload.update(fields)
    return client.post("/aiModelConfig/add", json=payload, headers=admin_headers).json()


def _cleanup(client, admin_headers) -> None:
    """把测试造出来的配置删干净。启用中的配置接口不允许直接删，先停用再删。"""
    for row in _list_configs(client, admin_headers, name=TEST_MARK):
        if TEST_MARK not in (row["name"] or ""):
            continue
        if row["enabled"] == "是":
            client.post("/aiModelConfig/updateEnabled",
                        json={"config_id": row["id"], "enabled": "否"}, headers=admin_headers)
        client.delete(f"/aiModelConfig/delete/{row['id']}", headers=admin_headers)


def test_seed_configs_cover_four_purposes(client, admin_headers):
    """初始化数据里四个用途各有一条启用中的配置。

    这条用例同时是一道体检：如果上一次跑测留下脏状态，某个用途没有启用中的配置了，
    它会带着补救办法报出来。
    """
    rows = _list_configs(client, admin_headers)
    enabled = {}
    for row in rows:
        if row["enabled"] == "是":
            enabled[row["model_purpose"]] = row
    for purpose in SEED_PURPOSES:
        assert purpose in enabled, (
            f"初始化数据里「{purpose}」用途没有启用中的配置，"
            f"请把这一条的配置重新启用（重新执行一次 paringbot.sql 里那四条初始化配置也行）")
    # 一个用途只留一条启用中的配置
    counts = {}
    for row in rows:
        if row["enabled"] == "是":
            counts[row["model_purpose"]] = counts.get(row["model_purpose"], 0) + 1
    assert all(count == 1 for count in counts.values()), "同一个用途出现了多条启用中的配置"


def test_purpose_options(client, admin_headers):
    """用途选项由后端给出，一个用途对应一个 Agent 角色。"""
    body = client.get("/aiModelConfig/purposeOptions", headers=admin_headers).json()
    assert body["code"] == "200"
    assert body["data"] == ["调度", "画像", "筛选", "审核"]


def test_api_key_is_masked_in_list(client, admin_headers):
    """列表里返回的是脱敏密钥，完整密钥不出后端。"""
    _cleanup(client, admin_headers)
    name = f"脱敏校验{TEST_MARK}"
    assert _add(client, admin_headers, name=name, api_key="sk-abcdefghijklmnop")["code"] == "200"
    assert _row_of(client, admin_headers, name)["api_key"] == "sk-a" + "*" * 8 + "mnop"
    _cleanup(client, admin_headers)


def test_unknown_purpose_is_rejected(client, admin_headers):
    """用途只能从四个角色里选，乱填的用途没有哪个角色会来取它。"""
    body = _add(client, admin_headers, name=f"用途校验{TEST_MARK}", model_purpose="话术生成")
    assert body["code"] == "500"
    assert "模型用途请选" in body["msg"]


def test_base_url_must_start_with_protocol(client, admin_headers):
    """接口地址少了协议头是最常见的一种填错，保存时就拦住。"""
    body = _add(client, admin_headers, name=f"地址校验{TEST_MARK}", base_url="api.deepseek.com/v1")
    assert body["code"] == "500"
    assert "http://" in body["msg"]


def test_temperature_range_is_checked(client, admin_headers):
    """温度只允许 0 到 2。"""
    body = _add(client, admin_headers, name=f"温度校验{TEST_MARK}", temperature=3)
    assert body["code"] == "500"
    assert "温度" in body["msg"]


def test_duplicate_name_is_rejected(client, admin_headers):
    """配置名称不能重复，重名之后页面上分不清说的是哪一条。"""
    _cleanup(client, admin_headers)
    name = f"重名校验{TEST_MARK}"
    assert _add(client, admin_headers, name=name)["code"] == "200"
    body = _add(client, admin_headers, name=name)
    assert body["code"] == "500"
    assert "不能重复" in body["msg"]
    _cleanup(client, admin_headers)


async def test_update_keeps_key_when_page_sends_masked_value(db):
    """弹窗里回填的是脱敏串，没重新输入密钥时不能把真密钥冲掉。"""
    config = await AiModelConfig.create(
        name=f"密钥保留{TEST_MARK}", model_purpose="画像",
        base_url="https://api.deepseek.com/v1", model_name="deepseek-chat",
        api_key="sk-realkey12345678", enabled="否")
    try:
        await model_config_service.update(config.id, {
            "id": config.id,
            "name": config.name,
            "model_purpose": "画像",
            "base_url": config.base_url,
            "model_name": config.model_name,
            # 页面上看到什么就交回什么，交回来的就是这串星号
            "api_key": model_config_service.mask_api_key(config.api_key),
            "enabled": "否",
        })
        await config.refresh_from_db()
        assert config.api_key == "sk-realkey12345678"
    finally:
        await AiModelConfig.filter(id=config.id).delete()


def test_enable_switches_other_config_of_same_purpose(client, admin_headers):
    """一个用途只留一条启用中的配置，新启用一条会把原来那条停掉。"""
    _cleanup(client, admin_headers)
    seed_row = _row_of(client, admin_headers, SEED_PORTRAIT_NAME)
    assert seed_row["enabled"] == "是"
    name = f"画像备用{TEST_MARK}"
    try:
        assert _add(client, admin_headers, name=name, enabled="是")["code"] == "200"
        enabled = [row for row in _list_configs(client, admin_headers, model_purpose="画像")
                   if row["enabled"] == "是"]
        assert len(enabled) == 1
        assert enabled[0]["name"] == name
        # 原来那条被自动停用了
        assert _row_of(client, admin_headers, SEED_PORTRAIT_NAME)["enabled"] == "否"
    finally:
        _cleanup(client, admin_headers)
        # 把初始化数据里的状态恢复回去，后面的用例和页面都还要用它
        client.post("/aiModelConfig/updateEnabled",
                    json={"config_id": seed_row["id"], "enabled": "是"}, headers=admin_headers)
        assert _row_of(client, admin_headers, SEED_PORTRAIT_NAME)["enabled"] == "是"


def test_enabled_config_cannot_be_deleted(client, admin_headers):
    """启用中的配置正被链路使用，接口拦下来并给出替代做法。"""
    seed_row = _row_of(client, admin_headers, SEED_PORTRAIT_NAME)
    body = client.delete(f"/aiModelConfig/delete/{seed_row['id']}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert "请先停用它" in body["msg"]
    # 拦下来之后配置还在
    assert _row_of(client, admin_headers, SEED_PORTRAIT_NAME)["enabled"] == "是"


def test_stopped_config_can_be_deleted(client, admin_headers):
    """停用中的配置可以删掉。"""
    _cleanup(client, admin_headers)
    name = f"可删除{TEST_MARK}"
    assert _add(client, admin_headers, name=name)["code"] == "200"
    row = _row_of(client, admin_headers, name)
    assert client.delete(f"/aiModelConfig/delete/{row['id']}",
                         headers=admin_headers).json()["code"] == "200"
    assert all(item["name"] != name for item in _list_configs(client, admin_headers, name=name))


def test_update_enabled_rejects_unknown_value(client, admin_headers):
    """启用状态只认是或否。"""
    seed_row = _row_of(client, admin_headers, SEED_PORTRAIT_NAME)
    body = client.post("/aiModelConfig/updateEnabled",
                       json={"config_id": seed_row["id"], "enabled": "可能是"},
                       headers=admin_headers).json()
    assert body["code"] == "500"
    assert "是或否" in body["msg"]


def test_connection_without_api_key(client, admin_headers):
    """没填密钥时在发请求之前就返回，并说清要先补密钥。"""
    _cleanup(client, admin_headers)
    name = f"缺少密钥{TEST_MARK}"
    assert _add(client, admin_headers, name=name)["code"] == "200"
    row = _row_of(client, admin_headers, name)
    body = client.post(f"/aiModelConfig/test/{row['id']}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "请先填写 API Key"
    _cleanup(client, admin_headers)


def test_connection_unknown_config(client, admin_headers):
    """配置不存在时说清刷新列表再试，而不是报一句模型调用失败。"""
    body = client.post("/aiModelConfig/test/2147483647", headers=admin_headers).json()
    assert body["code"] == "500"
    assert "未找到" in body["msg"]


def test_member_cannot_manage_model_config(client, user_headers):
    """模型配置是平台级配置，租客账号看不到也改不了。"""
    body = client.get("/aiModelConfig/selectPage", headers=user_headers).json()
    assert body["code"] == "403"


async def test_load_for_purpose_reports_missing_purpose(db):
    """按用途取不到启用中的配置时，报错要说清去哪启用。"""
    with pytest.raises(CustomException) as error:
        await model_factory.load_for_purpose("单元测试专用用途")
    assert "请先到【AI模型配置】" in error.value.message


async def test_load_for_purpose_reports_missing_key(db):
    """配置取到了但没填密钥时，要说清去补密钥，而不是到模型接口那里报一句英文。"""
    seed = await AiModelConfig.get(model_purpose="画像", enabled="是")
    config = await AiModelConfig.create(
        name=f"未填密钥{TEST_MARK}", model_purpose="画像",
        base_url="https://api.deepseek.com/v1", model_name="deepseek-chat", enabled="否")
    try:
        await model_config_service.update_enabled(config.id, "是")
        with pytest.raises(CustomException) as error:
            await model_factory.load_for_purpose("画像")
        assert "API Key" in error.value.message
    finally:
        await AiModelConfig.filter(id=config.id).delete()
        await AiModelConfig.filter(id=seed.id).update(enabled="是")


async def test_load_for_purpose_returns_the_enabled_one(db):
    """同一个用途下只有一条启用时，按用途取到的就是它。"""
    seed = await AiModelConfig.get(model_purpose="画像", enabled="是")
    config = await AiModelConfig.create(
        name=f"用途取用{TEST_MARK}", model_purpose="画像",
        base_url="https://api.deepseek.com/v1", model_name="deepseek-chat",
        api_key="sk-unittestkey", enabled="否")
    try:
        await model_config_service.update_enabled(config.id, "是")
        loaded = await model_factory.load_for_purpose("画像")
        assert loaded.id == config.id
    finally:
        await AiModelConfig.filter(id=config.id).delete()
        # 恢复初始化数据里那条的启用状态
        await AiModelConfig.filter(id=seed.id).update(enabled="是")
