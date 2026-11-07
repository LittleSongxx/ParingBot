"""审核软冲突的代码兜底 / 候选名单字段的纯单元测试（不连数据库、不调模型）。

2026-11 质量根因：8 个被否决候选全部硬合规，但审核官把兴趣标签“养鱼/爬宠”
当成真实养宠证据，与 has_pet=无 的档案字段矛盾，造成假否决。
这里锁定两件事：
1) 候选名单必须把“吸烟/宠物”作为档案事实给审核官；
2) PREFERENCE_CONFLICT 的理由与档案硬事实矛盾时，代码要能识别并改回通过。
"""
from datetime import datetime
from types import SimpleNamespace

from service import auditor_service


def _member(**overrides):
    base = {
        "id": 1, "nickname": "小 A", "gender": "男", "birth_date": datetime(1994, 3, 12),
        "rent_budget": 3000, "tidiness": "整洁", "store_id": 1,
        "schedule_type": "正常作息", "smoking": "不吸烟", "has_pet": "无",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _row(member, found_round=1):
    return SimpleNamespace(candidate_member_id=member.id, found_round=found_round), member


def _preference(**overrides):
    base = {"pet_accept": "不接受", "budget_min": 2500, "budget_max": 4000}
    base.update(overrides)
    return SimpleNamespace(**base)


class TestCandidateTextFacts:
    def test_candidate_text_includes_smoking_and_pet(self):
        text = auditor_service.candidate_text([_row(_member())])
        assert "吸烟" in text and "宠物" in text
        assert "不吸烟" in text and "无" in text

    def test_instruction_marks_fields_as_authoritative(self):
        text = auditor_service.instruction([_row(_member())], pending=3, batch_no=1)
        assert "档案事实" in text
        assert "不能当作养宠证据" in text


class TestSoftRejectContradiction:
    def test_pet_reason_but_profile_says_no_pet(self):
        note = auditor_service.soft_reject_contradiction(
            _member(), _member(has_pet="无"), _preference(),
            "PREFERENCE_CONFLICT", "兴趣为养鱼（实际饲养宠物），与申请方不接受养宠冲突")
        assert note and "has_pet=无" in note

    def test_pet_reason_with_other_conflict_is_not_overridden(self):
        """理由同时提到作息冲突时不做自动改判，交给人工/下一轮。"""
        note = auditor_service.soft_reject_contradiction(
            _member(), _member(has_pet="无"), _preference(),
            "PREFERENCE_CONFLICT",
            "兴趣为养鱼，且双方作息冲突（夜猫子 vs 早睡早起）")
        assert note is None

    def test_pet_reason_when_candidate_really_has_pet(self):
        note = auditor_service.soft_reject_contradiction(
            _member(), _member(has_pet="有"), _preference(),
            "PREFERENCE_CONFLICT", "候选养狗，申请方不接受宠物")
        assert note is None

    def test_smoking_reason_but_profile_says_non_smoker(self):
        note = auditor_service.soft_reject_contradiction(
            _member(), _member(smoking="不吸烟"), _preference(),
            "PREFERENCE_CONFLICT", "候选经常在屋里吸烟，申请方不吸烟")
        assert note and "smoking=不吸烟" in note

    def test_budget_reason_but_budget_in_range(self):
        note = auditor_service.soft_reject_contradiction(
            _member(), _member(rent_budget=3200), _preference(),
            "PREFERENCE_CONFLICT", "候选预算超出租客预算范围")
        assert note and "预算在申请方范围内" in note

    def test_other_reject_code_is_ignored(self):
        note = auditor_service.soft_reject_contradiction(
            _member(), _member(), _preference(), "MISMATCH_HARD", "候选养鱼")
        assert note is None
