from tortoise import fields
from tortoise.models import Model


class InterestTag(Model):
    """兴趣标签词表。

    画像师给租客打兴趣标签、筛选官按兴趣检索候选，都只认这张表里的词，
    模型不许自造标签。
    """

    id = fields.IntField(pk=True)
    # 标签名，唯一索引 uk_interest_tag_name
    tag_name = fields.CharField(max_length=50, unique=True)
    # 运动 / 影音 / 美食 / 旅行 / 宠物 / 阅读 / 游戏 / 艺术
    category = fields.CharField(max_length=20)
    enabled = fields.CharField(max_length=10, default="是")
    sort = fields.IntField(default=0)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "interest_tag"


class MemberMoment(Model):
    """租客动态表，画像师的主要非结构化数据源。"""

    id = fields.IntField(pk=True)
    member_id = fields.IntField()
    content = fields.TextField()
    # 动态配图路径，逗号分隔，可以为空
    image_paths = fields.TextField(null=True)
    publish_time = fields.DatetimeField(null=True)
    # 公开 / 仅匹配室友可见
    visible = fields.CharField(max_length=20, default="公开")
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "member_moment"
