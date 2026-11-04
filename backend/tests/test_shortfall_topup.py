"""短交付补筛门禁的纯逻辑测试。"""
from ai import graph


def test_topup_when_pool_enough_but_passed_short():
    assert graph.needs_shortfall_topup({"passed": 7, "total": 9, "pending": 0}, 8, 0, 2)


def test_no_topup_when_pool_too_small():
    assert not graph.needs_shortfall_topup({"passed": 4, "total": 4, "pending": 0}, 8, 0, 2)


def test_no_topup_when_pending_or_relax_exhausted():
    assert not graph.needs_shortfall_topup({"passed": 7, "total": 9, "pending": 1}, 8, 0, 2)
    assert not graph.needs_shortfall_topup({"passed": 7, "total": 9, "pending": 0}, 8, 2, 2)
