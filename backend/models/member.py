from tortoise import fields
from tortoise.models import Model


class MemberProfile(Model):
    """租客档案表。

    一个账号一份档案。年龄不存字段，页面展示与候选筛选都按 birth_date 现算，
    避免生日改了年龄不跟着变。档案只有审核通过之后才会进入候选池。
    """

    id = fields.IntField(pk=True)
    # 一个账号只能有一份租客档案，唯一索引 uk_member_profile_user
    user_id = fields.IntField(unique=True)
    nickname = fields.CharField(max_length=100)
    # 男 / 女。合租按同性匹配，候选只在同性别的租客里找
    gender = fields.CharField(max_length=10)
    # 出生日期，只用到日期部分，按全表口径仍用 DatetimeField
    birth_date = fields.DatetimeField(null=True)
    # 月租预算，单位元
    rent_budget = fields.IntField(null=True)
    # 整洁度：随意 / 一般 / 整洁 / 洁癖
    tidiness = fields.CharField(max_length=20, null=True)
    occupation = fields.CharField(max_length=100, null=True)
    # 计划租期：3个月以下 / 3-6个月 / 6-12个月 / 1-2年 / 2年以上
    lease_term = fields.CharField(max_length=20, null=True)
    # 意向门店编码，取值来自代码里固定的 20 家门店清单，不做门店表
    store_id = fields.IntField(null=True)
    # 作息：早睡早起 / 正常作息 / 夜猫子
    schedule_type = fields.CharField(max_length=20, null=True)
    # 是否养宠：有 / 无
    has_pet = fields.CharField(max_length=10, null=True)
    # 吸烟：不吸烟 / 偶尔 / 经常
    smoking = fields.CharField(max_length=10, null=True)
    # 自我介绍，画像师提取标签的主要数据源
    self_intro = fields.TextField(null=True)
    # 室友期望，筛选官判断优先放宽哪个维度时会读它
    roommate_expectation = fields.TextField(null=True)
    # 兴趣标签，逗号分隔，取值必须来自 interest_tag 词表
    interest_tags = fields.CharField(max_length=500, null=True)
    # 生活照路径，逗号分隔
    photo_paths = fields.TextField(null=True)
    # 待审核 / 已通过 / 已驳回
    audit_status = fields.CharField(max_length=20, default="待审核")
    audit_remark = fields.CharField(max_length=500, null=True)
    audit_time = fields.DatetimeField(null=True)
    # 是 / 否。审核通过之后管理员仍可以停用这份档案
    enabled = fields.CharField(max_length=10, default="是")
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "member_profile"
