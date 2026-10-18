from tortoise import fields
from tortoise.models import Model


class User(Model):
    """用户表。

    管理员和租客统一存这里，通过 role 字段区分：ADMIN 进管理端，
    USER 进用户端。这个 role 管的是「谁能看到哪个页面」，
    和 agent_definition 里那套 Agent 角色不是一回事。
    """

    id = fields.IntField(pk=True)
    # 登录账号，unique=True 对应表上的唯一索引 uk_user_username
    username = fields.CharField(max_length=100, unique=True)
    password = fields.CharField(max_length=255)
    name = fields.CharField(max_length=100)
    avatar = fields.CharField(max_length=500, null=True)
    # ADMIN 管理员 / USER 租客
    role = fields.CharField(max_length=30, default="USER")
    phone = fields.CharField(max_length=30, null=True)
    email = fields.CharField(max_length=100, null=True)
    # NORMAL 正常 / DISABLED 停用
    status = fields.CharField(max_length=20, default="NORMAL")
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "user"
