from tortoise import fields
from tortoise.models import Model


class RoommatePreference(Model):
    """合住偏好表。

    每个维度成对出现：一个取值列和一个 _required 列。_required 取「必须 / 加分」，
    筛选官只能放宽标为「加分」的维度，「必须」的项任何情况下都不许动。
    """

    id = fields.IntField(pk=True)
    # 一个租客一条偏好，唯一索引 uk_roommate_preference_member
    member_id = fields.IntField(unique=True)
    age_min = fields.IntField(null=True)
    age_max = fields.IntField(null=True)
    age_required = fields.CharField(max_length=10, default="加分")
    # 室友的月租预算区间，单位元。预算接近的人才租得起同一档房型
    budget_min = fields.IntField(null=True)
    budget_max = fields.IntField(null=True)
    budget_required = fields.CharField(max_length=10, default="加分")
    # 最低整洁度：随意 / 一般 / 整洁 / 洁癖
    tidiness_min = fields.CharField(max_length=20, null=True)
    tidiness_required = fields.CharField(max_length=10, default="加分")
    # 同门店 / 同片区 / 不限
    store_scope = fields.CharField(max_length=20, default="不限")
    store_required = fields.CharField(max_length=10, default="加分")
    # 可以接受的作息，多选用逗号分隔，例如「早睡早起,正常作息」
    schedule_accept = fields.CharField(max_length=50, null=True)
    schedule_required = fields.CharField(max_length=10, default="加分")
    # 最短租期，取值同 member_profile.lease_term
    lease_min = fields.CharField(max_length=20, null=True)
    lease_required = fields.CharField(max_length=10, default="加分")
    # 室友养宠的接受度：接受 / 不接受 / 无所谓
    pet_accept = fields.CharField(max_length=20, null=True)
    pet_required = fields.CharField(max_length=10, default="加分")
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "roommate_preference"
