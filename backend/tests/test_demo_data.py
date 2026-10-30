"""种子库演示数据的一致性测试。

这些断言直接跑在真实种子库上（pytest 会话共用开发库），不造演示数据、不依赖模型：

1. 没有「通过但性别与申请方不同」的候选；
2. 没有「通过但双向必须项复核不通过」的候选（模型误判、规则变化前的历史遗留）；
3. 两个种子任务的 delivered_count 等于当前 deliverable() 口径算出来的交付数；
4. 两次运行记录里的总结数字与候选池现查结果一致，并带历史迁移说明。

历史数据由 deploy/mysql/init/03-data-fixes.sql 迁移：task 40 的 6 名异性候选、
task 78 的「谦砚」按当前硬规则改判否决，交付数分别调整为 4 / 7。种子库没重建时
这些断言会失败，属于预期——它守的就是「迁移脚本真的执行过、页面数字才可信」。
"""

import re

from models import AgentRun, MatchCandidate, MatchTask, MemberProfile
from service import auditor_service, match_service

# 经过历史数据迁移的两个种子任务（task 40 / task 78）
SEED_TASK_NOS = ("MATCH-20261004124819-8ce9b7", "MATCH-20261006225835-24aadc")
# 迁移后的目标交付人数，和 03-data-fixes.sql 里的 delivered_count 对齐
SEED_DELIVERED = {"MATCH-20261004124819-8ce9b7": 4,
                  "MATCH-20261006225835-24aadc": 7}
# 运行总结里固定的数字段落，由 match_service._summary 拼出来
SUMMARY_PATTERN = re.compile(
    r"候选池累计 (\d+) 人，通过审核 (\d+) 人，否决 (\d+) 人，交付 (\d+) 人（要求 (\d+) 人）")


async def _seed_tasks() -> list[MatchTask]:
    """只取两个种子任务：测试用例自己造的任务（编号带测试标记）不参与断言。"""
    tasks = await MatchTask.filter(task_no__in=list(SEED_TASK_NOS))
    return sorted(tasks, key=lambda task: task.id)


async def test_seed_tasks_are_present(db):
    """迁移脚本依赖的两条种子任务必须在库里，否则后面的断言无从谈起。"""
    tasks = await _seed_tasks()
    assert [task.task_no for task in tasks] == list(SEED_TASK_NOS)


async def test_no_passed_candidate_of_another_gender(db):
    """种子库里不允许存在「通过但和申请方性别不同」的候选。"""
    for task in await _seed_tasks():
        applicant = await MemberProfile.get(id=task.member_id)
        rows = await MatchCandidate.filter(task_id=task.id, audit_status="通过")
        members = {member.id: member for member in await MemberProfile.filter(
            id__in=[row.candidate_member_id for row in rows])}
        bad = [row.id for row in rows
               if members[row.candidate_member_id].gender != applicant.gender]
        assert bad == [], f"task {task.id} 仍有异性「通过」候选：{bad}"


async def test_no_passed_candidate_violates_the_must_dimensions(db):
    """种子库里不允许存在「通过但双向必须项复核不通过」的候选。"""
    for task in await _seed_tasks():
        applicant = await MemberProfile.get(id=task.member_id)
        rows = await MatchCandidate.filter(task_id=task.id, audit_status="通过")
        records = await auditor_service.recheck_rows(applicant, rows)
        detail = [f"候选行 {item.row.id}：{item.rejected_because()}" for item in records]
        assert detail == [], f"task {task.id} 仍有复核不通过的「通过」候选：{detail}"


async def test_task_delivered_count_matches_deliverable(db):
    """任务上的 delivered_count 必须等于当前交付口径算出来的交付数。"""
    for task in await _seed_tasks():
        rows, _note = await match_service.deliverable(task.id)
        delivered = min(len(rows), task.deliver_count)
        assert delivered == SEED_DELIVERED[task.task_no]
        assert task.delivered_count == delivered

    # 总数也对得上：迁移后 task 40 = 33 人、通过 4、否决 29；task 78 = 15/7/8
    task40 = next(task for task in await _seed_tasks() if task.id == 40)
    pool40 = await MatchCandidate.filter(task_id=task40.id)
    assert len(pool40) == 33
    assert len([row for row in pool40 if row.audit_status == "通过"]) == 4
    assert len([row for row in pool40 if row.audit_status == "否决"]) == 29
    task78 = next(task for task in await _seed_tasks() if task.id == 78)
    pool78 = await MatchCandidate.filter(task_id=task78.id)
    assert len(pool78) == 15
    assert len([row for row in pool78 if row.audit_status == "通过"]) == 7
    assert len([row for row in pool78 if row.audit_status == "否决"]) == 8


async def test_run_summary_matches_the_database(db):
    """运行总结里的数字与候选池现查结果一致，并带「历史记录已按当前口径迁移」。"""
    for task in await _seed_tasks():
        run = await AgentRun.filter(
            task_id=task.id, run_type=match_service.RUN_TYPE).order_by("-id").first()
        assert run is not None, f"task {task.id} 没有匹配编排运行记录"
        summary = run.output_summary or ""
        assert "历史记录已按当前口径迁移" in summary, summary
        matched = SUMMARY_PATTERN.search(summary)
        assert matched is not None, summary
        total, passed, rejected, delivered, deliver_count = map(int, matched.groups())

        pool = await MatchCandidate.filter(task_id=task.id)
        passed_rows, _note = await match_service.deliverable(task.id)
        assert total == len(pool)
        assert passed == len([row for row in pool if row.audit_status == "通过"])
        assert rejected == len([row for row in pool if row.audit_status == "否决"])
        assert delivered == min(len(passed_rows), task.deliver_count)
        assert deliver_count == task.deliver_count
        assert run.current_round == task.total_round
