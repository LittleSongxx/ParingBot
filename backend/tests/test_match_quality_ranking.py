"""质量感知排序惩罚 / 质量门禁的纯单元测试（不连数据库、不调模型）。"""
from datetime import date
from types import SimpleNamespace

from service import match_service


def _member(**overrides):
    base = {
        "store_id": 1, "schedule_type": "正常作息", "lease_term": "1-2年",
        "rent_budget": 3000, "birth_date": date(1994, 3, 12), "tidiness": "整洁",
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


class QualityRankingTest:
    def test_smoking_conflict_gets_penalty(self):
        applicant, preference = _member(), _preference()
        clean = match_service._suitability_score(applicant, _member(), preference)
        smoking = match_service._suitability_score(
            applicant, _member(smoking="经常"), preference)
        assert smoking < clean

    def test_tidiness_gap_gets_penalty(self):
        applicant, preference = _member(), _preference(tidiness_min="整洁")
        clean = match_service._suitability_score(applicant, _member(), preference)
        messy = match_service._suitability_score(
            applicant, _member(tidiness="随意"), preference)
        assert messy < clean

    def test_pet_conflict_gets_penalty(self):
        applicant, preference = _member(), _preference(pet_accept="不接受")
        clean = match_service._suitability_score(applicant, _member(), preference)
        pet = match_service._suitability_score(
            applicant, _member(has_pet="有"), preference)
        assert pet < clean

    def test_tidiness_closeness_tiebreak(self):
        applicant, preference = _member(tidiness="整洁"), _preference(tidiness_min="一般")
        same = match_service._suitability_score(applicant, _member(tidiness="整洁"), preference)
        near = match_service._suitability_score(applicant, _member(tidiness="一般"), preference)
        far = match_service._suitability_score(applicant, _member(tidiness="随意"), preference)
        assert same > near > far

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
