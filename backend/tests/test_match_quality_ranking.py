"""交付排序分 / 质量门禁的纯单元测试（不连数据库、不调模型）。"""
from datetime import datetime
from types import SimpleNamespace

from service import match_service


def _member(**overrides):
    base = {
        "store_id": 1, "schedule_type": "正常作息", "lease_term": "1-2年",
        "rent_budget": 3000, "birth_date": datetime(1994, 3, 12), "tidiness": "整洁",
        "smoking": "不吸烟", "has_pet": "无", "interest_tags": "看电影,跑步",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _preference(**overrides):
    base = {
        "schedule_accept": "正常作息", "budget_min": 2500, "budget_max": 4000,
        "age_min": 22, "age_max": 40, "tidiness_min": "整洁", "pet_accept": "接受",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestQualityRanking:
    def test_suitability_score_ignores_quality_penalties(self):
        """质量感知惩罚已回退：吸烟/养宠不再扣分，整洁度只保留原有“达标 +1”。"""
        applicant = _member()

        preference = _preference()
        clean = match_service._suitability_score(applicant, _member(), preference)
        for smoking in ("经常", "偶尔"):
            assert match_service._suitability_score(
                applicant, _member(smoking=smoking), preference) == clean

        pet_preference = _preference(pet_accept="不接受")
        clean = match_service._suitability_score(applicant, _member(), pet_preference)
        assert match_service._suitability_score(
            applicant, _member(has_pet="有"), pet_preference) == clean

        # 不达标候选本来就拿不到原有“达到最低档 +1”，只应落后 1 分；
        # 65d011a 的 -2 档位惩罚回退后不应再多扣（回退前这里会是 3 分差）。
        tidy_preference = _preference(tidiness_min="整洁")
        meets = match_service._suitability_score(
            applicant, _member(tidiness="整洁"), tidy_preference)
        below = match_service._suitability_score(
            applicant, _member(tidiness="随意"), tidy_preference)
        assert meets - below == 1

    def test_severity_gate(self):
        applicant, preference = _member(), _preference(pet_accept="不接受")
        assert match_service._severe_quality_conflict(
            applicant, _member(smoking="经常"), _preference())
        assert match_service._severe_quality_conflict(
            applicant, _member(tidiness="随意"), _preference(tidiness_min="整洁"))
        assert match_service._severe_quality_conflict(
            applicant, _member(has_pet="有"), preference)
        assert not match_service._severe_quality_conflict(
            applicant, _member(), _preference())

    def test_quality_gate_defaults_off(self):
        """QUALITY_GATE 是显式 A/B 实验开关，默认关闭（settings 读 env，默认 off）。"""
        from settings import QUALITY_GATE

        assert QUALITY_GATE is False
