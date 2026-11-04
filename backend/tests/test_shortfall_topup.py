"""短交付补筛门禁的纯逻辑测试。"""
from ai import graph


def test_topup_when_pool_enough_but_passed_short():
    assert graph.needs_shortfall_topup({"passed": 7, "total": 9, "pending": 0}, 8, 0, 2)


def test_no_topup_when_pool_too_small():
    assert not graph.needs_shortfall_topup({"passed": 4, "total": 4, "pending": 0}, 8, 0, 2)


def test_no_topup_when_pending_or_relax_exhausted():
    assert not graph.needs_shortfall_topup({"passed": 7, "total": 9, "pending": 1}, 8, 0, 2)
    assert not graph.needs_shortfall_topup({"passed": 7, "total": 9, "pending": 0}, 8, 2, 2)


def test_stagnant_rounds_and_stop():
    assert graph.next_stagnant_rounds("a", "a", 0) == 1
    assert graph.next_stagnant_rounds("a", "a", 1) == 2
    assert graph.next_stagnant_rounds("a", "b", 5) == 0
    assert graph.should_stop_on_stagnation(2, {"total": 4, "passed": 4, "pending": 0}, 8)
    assert not graph.should_stop_on_stagnation(1, {"total": 4, "passed": 4, "pending": 0}, 8)
    assert not graph.should_stop_on_stagnation(2, {"total": 8, "passed": 4, "pending": 0}, 8)
