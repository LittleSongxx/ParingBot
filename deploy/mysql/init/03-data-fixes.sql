-- 历史数据一致性迁移：把存量候选池里与当前硬规则冲突的「通过」改判否决，
-- 并把受影响任务、运行记录里的交付口径改成与当前 deliverable() 一致。
--
-- 背景：此前的修复只对新运行生效，历史结论不追溯，会出现页面显示「通过 10 人、
-- 交付 8 人」但其中 6 人与申请方性别不同、或候选方必须项其实不满足的矛盾
-- （analysis/05-backend-ai-issues.md §2、A-01/A-10）。本脚本只动 task 40 / task 78
-- 及其候选和运行记录，另补三条缺失索引，不改其它业务数据。
--
-- 幂等：改判条件都带 audit_status='通过'，重复执行不会重复改；
-- 任务与运行记录按目标值重写；索引先查 information_schema，存在同名索引就跳过。
-- 本文件含中文：必须显式声明连接字符集，否则 mysql 客户端按 latin1 解释 UTF-8 会写坏。
SET NAMES utf8mb4;

-- ---------------------------------------------------------------------------
-- 1. task 40（run 38）：6 名与申请方性别不同的「通过」按「合租只找同性」改判否决
--    改判后通过 4 人、否决 29 人，交付人数按当前 deliverable() 口径改为 4。
-- ---------------------------------------------------------------------------
UPDATE `match_candidate` AS mc
JOIN `member_profile` AS cand ON cand.`id` = mc.`candidate_member_id`
JOIN `match_task` AS mt ON mt.`id` = mc.`task_id`
JOIN `member_profile` AS applicant ON applicant.`id` = mt.`member_id`
SET mc.`audit_status` = '否决',
    mc.`reject_code` = 'MISMATCH_HARD',
    mc.`reject_reason` = '历史迁移：合租只找同性，候选方与申请方性别不同，原「通过」按当前硬规则改判否决',
    mc.`update_time` = NOW()
WHERE mc.`task_id` = 40
  AND mc.`audit_status` = '通过'
  AND cand.`gender` <> applicant.`gender`;

UPDATE `match_task`
SET `delivered_count` = 4, `update_time` = NOW()
WHERE `id` = 40 AND `task_no` = 'MATCH-20261004124819-8ce9b7';

UPDATE `agent_run`
SET `output_summary` = '调度 8 轮，候选池累计 33 人，通过审核 4 人，否决 29 人，交付 4 人（要求 8 人）；收尾原因：主管判断可以收尾；历史记录已按当前口径迁移'
WHERE `id` = 38 AND `run_no` = 'MATCH-20261004124819-178b0a';

-- ---------------------------------------------------------------------------
-- 2. task 78（run 63）：「谦砚」（candidate_member_id=177）的预算必须项不满足，
--    按审核复核口径改判否决；通过 7 人、否决 8 人，交付人数改为 7。
-- ---------------------------------------------------------------------------
UPDATE `match_candidate`
SET `audit_status` = '否决',
    `reject_code` = 'MISMATCH_HARD',
    `reject_reason` = '历史迁移：候选「谦砚」要求预算 1500-3000 元（必须），申请方预算 3500 元超出上限，硬性预算不满足，原「通过」改判否决',
    `update_time` = NOW()
WHERE `task_id` = 78
  AND `candidate_member_id` = 177
  AND `audit_status` = '通过';

UPDATE `match_task`
SET `delivered_count` = 7, `update_time` = NOW()
WHERE `id` = 78 AND `task_no` = 'MATCH-20261006225835-24aadc';

UPDATE `agent_run`
SET `output_summary` = '调度 4 轮，候选池累计 15 人，通过审核 7 人，否决 8 人，交付 7 人（要求 8 人）；收尾原因：主管判断可以收尾；候选「谦砚」因候选方必须项（预算）不满足改判否决，交付人数由 8 人调整为 7 人。历史记录已按当前口径迁移'
WHERE `id` = 63 AND `run_no` = 'MATCH-20261006225835-5cdd63';

-- ---------------------------------------------------------------------------
-- 3. 缺失索引：交付/复核与页面查询按这些列过滤和排序。
--    01 建表时没有复合索引；这里按名字判断，已存在就跳过（可重复执行）。
-- ---------------------------------------------------------------------------

-- 候选池按任务取一轮筛出来的人（deliverable / 漏斗 / 候选页）
SET @has_index := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'match_candidate'
      AND INDEX_NAME = 'idx_match_candidate_task_round'
);
SET @ddl := IF(@has_index = 0,
    'ALTER TABLE `match_candidate` ADD INDEX `idx_match_candidate_task_round` (`task_id`, `found_round`)',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 运行时间线按步骤序号稳定排序（round_rows / trace timeline）
SET @has_index := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'agent_step'
      AND INDEX_NAME = 'idx_agent_step_run_step'
);
SET @ddl := IF(@has_index = 0,
    'ALTER TABLE `agent_step` ADD INDEX `idx_agent_step_run_step` (`run_id`, `step_index`)',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 候选检索按「同性 + 档案已通过 + 启用」过滤
SET @has_index := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'member_profile'
      AND INDEX_NAME = 'idx_member_profile_gender_audit'
);
SET @ddl := IF(@has_index = 0,
    'ALTER TABLE `member_profile` ADD INDEX `idx_member_profile_gender_audit` (`gender`, `audit_status`, `enabled`)',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
