-- 演示数据：补齐 holdout v2 覆盖门店的候选流动性（门店级，不按具体租客定制）。
-- 补齐后 v2 成为验证集，应新建 holdout v3。
SET NAMES utf8mb4;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-21', `rent_budget`=3600, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在漕河泾做销售，计划住一年左右；作息正常，平时打篮球。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=129;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=129;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-21', `rent_budget`=3600, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在漕河泾做销售，计划住一年左右；作息正常，平时打篮球。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=131;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=131;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-21', `rent_budget`=3600, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在漕河泾做销售，计划住一年左右；作息正常，平时打篮球。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=141;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=141;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-21', `rent_budget`=3600, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在漕河泾做销售，计划住一年左右；作息正常，平时打篮球。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=146;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=146;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-21', `rent_budget`=3600, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在漕河泾做销售，计划住一年左右；作息正常，平时打篮球。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=147;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=147;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-21', `rent_budget`=3600, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在漕河泾做销售，计划住一年左右；作息正常，平时打篮球。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=151;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=151;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-21', `rent_budget`=3600, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在漕河泾做销售，计划住一年左右；作息正常，平时打篮球。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=152;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=152;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2001-11-03', `rent_budget`=3000, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近实习三个月，作息正常、爱干净，实习结束可能换城市。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=171;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=171;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2001-11-03', `rent_budget`=3000, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近实习三个月，作息正常、爱干净，实习结束可能换城市。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=172;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=172;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2001-11-03', `rent_budget`=3000, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近实习三个月，作息正常、爱干净，实习结束可能换城市。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=174;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=174;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2001-11-03', `rent_budget`=3000, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近实习三个月，作息正常、爱干净，实习结束可能换城市。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=176;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=176;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2001-11-03', `rent_budget`=3000, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近实习三个月，作息正常、爱干净，实习结束可能换城市。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=178;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=178;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2001-11-03', `rent_budget`=3000, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近实习三个月，作息正常、爱干净，实习结束可能换城市。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=179;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=179;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2001-11-03', `rent_budget`=3000, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近实习三个月，作息正常、爱干净，实习结束可能换城市。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=184;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=184;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2001-11-03', `rent_budget`=3000, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近实习三个月，作息正常、爱干净，实习结束可能换城市。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=186;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=186;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-08-19', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在新江湾附近做厨师，预算不高，计划长住一年；作息正常、不吸烟。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=153;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=153;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-08-19', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在新江湾附近做厨师，预算不高，计划长住一年；作息正常、不吸烟。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=154;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=154;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-08-19', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在新江湾附近做厨师，预算不高，计划长住一年；作息正常、不吸烟。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=155;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=155;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-08-19', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在新江湾附近做厨师，预算不高，计划长住一年；作息正常、不吸烟。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=158;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=158;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-08-19', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在新江湾附近做厨师，预算不高，计划长住一年；作息正常、不吸烟。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=160;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=160;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-08-19', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在新江湾附近做厨师，预算不高，计划长住一年；作息正常、不吸烟。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=161;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=161;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-08-19', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在新江湾附近做厨师，预算不高，计划长住一年；作息正常、不吸烟。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=162;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=162;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-08-19', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在新江湾附近做厨师，预算不高，计划长住一年；作息正常、不吸烟。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=164;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=164;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-25', `rent_budget`=3800, `tidiness`='整洁',
    `store_id`=19, `schedule_type`='夜猫子', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在虹桥附近做设计，晚上经常画图到深夜，早上起得晚；不吸烟、不养宠物。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=188;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=32, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=188;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-25', `rent_budget`=3800, `tidiness`='整洁',
    `store_id`=19, `schedule_type`='夜猫子', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在虹桥附近做设计，晚上经常画图到深夜，早上起得晚；不吸烟、不养宠物。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=192;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=32, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=192;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-25', `rent_budget`=3800, `tidiness`='整洁',
    `store_id`=19, `schedule_type`='夜猫子', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在虹桥附近做设计，晚上经常画图到深夜，早上起得晚；不吸烟、不养宠物。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=193;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=32, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=193;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-25', `rent_budget`=3800, `tidiness`='整洁',
    `store_id`=19, `schedule_type`='夜猫子', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在虹桥附近做设计，晚上经常画图到深夜，早上起得晚；不吸烟、不养宠物。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=198;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=32, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=198;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-25', `rent_budget`=3800, `tidiness`='整洁',
    `store_id`=19, `schedule_type`='夜猫子', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在虹桥附近做设计，晚上经常画图到深夜，早上起得晚；不吸烟、不养宠物。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=199;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=32, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=199;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-25', `rent_budget`=3800, `tidiness`='整洁',
    `store_id`=19, `schedule_type`='夜猫子', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在虹桥附近做设计，晚上经常画图到深夜，早上起得晚；不吸烟、不养宠物。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=205;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=32, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=205;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-25', `rent_budget`=3800, `tidiness`='整洁',
    `store_id`=19, `schedule_type`='夜猫子', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在虹桥附近做设计，晚上经常画图到深夜，早上起得晚；不吸烟、不养宠物。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=207;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=32, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=207;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-25', `rent_budget`=3800, `tidiness`='整洁',
    `store_id`=19, `schedule_type`='夜猫子', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在虹桥附近做设计，晚上经常画图到深夜，早上起得晚；不吸烟、不养宠物。', `roommate_expectation`='希望室友作息合拍、好沟通，预算和租期对得上。'
WHERE `id`=208;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=32, `age_required`='必须',
    `budget_min`=3000, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同片区', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=208;

