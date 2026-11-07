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
    def test_smoking_penalty(self):
        """2026-11 根因：不吸烟申请方遇到经常/偶尔吸烟的候选必须降权。"""
        applicant, preference = _member(), _preference()
        clean = match_service._suitability_score(applicant, _member(), preference)
        occasional = match_service._suitability_score(
            applicant, _member(smoking="偶尔"), preference)
        frequent = match_service._suitability_score(
            applicant, _member(smoking="经常"), preference)
        assert occasional == clean - 1
        assert frequent == clean - 3

    def test_pet_penalty_only_when_pets_not_accepted(self):
        applicant = _member()
        strict = _preference(pet_accept="不接受")
        clean = match_service._suitability_score(applicant, _member(), strict)
        with_pet = match_service._suitability_score(
            applicant, _member(has_pet="有"), strict)
        assert with_pet == clean - 3
        # 申请方接受宠物时不扣分
        lenient = _preference(pet_accept="接受")
        clean_lenient = match_service._suitability_score(applicant, _member(), lenient)
        pet_lenient = match_service._suitability_score(
            applicant, _member(has_pet="有"), lenient)
        assert pet_lenient == clean_lenient

    def test_budget_closeness_adds_point(self):
        """预算都在区间内时，越接近申请方预算越靠前，避免 21% 同分。"""
        applicant, preference = _member(rent_budget=3000), _preference()
        near = match_service._suitability_score(
            applicant, _member(rent_budget=3100), preference)
        far = match_service._suitability_score(
            applicant, _member(rent_budget=3900), preference)
        assert near == far + 1

    def test_age_closeness_adds_point(self):
        applicant, preference = _member(), _preference()
        near = match_service._suitability_score(
            applicant, _member(birth_date=datetime(1994, 6, 1)), preference)
        far = match_service._suitability_score(
            applicant, _member(birth_date=datetime(1988, 6, 1)), preference)
        assert near == far + 1

    def test_tiebreak_fields_are_exposed(self):
        applicant, preference = _member(), _preference(pet_accept="不接受")
        clean = match_service._compat_penalties(applicant, _member(), preference)
        assert clean["smoking"] == 0 and clean["pet"] == 0
        assert clean["budget_gap"] == 0
        worse = match_service._compat_penalties(
            applicant, _member(smoking="经常", has_pet="有", rent_budget=5000), preference)
        assert worse["smoking"] == 3
        assert worse["pet"] == 3
        assert worse["budget_gap"] == 2000

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
        """QUALITY_GATE 仍是显式 A/B 实验开关，默认关闭；新惩罚只进排序分。"""
        from settings import QUALITY_GATE

        assert QUALITY_GATE is False
