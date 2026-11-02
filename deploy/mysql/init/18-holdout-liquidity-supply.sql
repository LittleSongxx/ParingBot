-- 演示数据：补齐 holdout 覆盖门店的候选流动性（不针对具体租客的精确偏好）。
-- 补齐后 holdout 作为验证集会被部分影响，后续应新建 holdout v2。
SET NAMES utf8mb4;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-08-20', `rent_budget`=4800, `tidiness`='整洁',
    `store_id`=17, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在曹杨路附近做公司法务，计划长住一到两年；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=49;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=36, `age_required`='必须',
    `budget_min`=4000, `budget_max`=5800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=49;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-08-20', `rent_budget`=4800, `tidiness`='整洁',
    `store_id`=17, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在曹杨路附近做公司法务，计划长住一到两年；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=54;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=36, `age_required`='必须',
    `budget_min`=4000, `budget_max`=5800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=54;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-08-20', `rent_budget`=4800, `tidiness`='整洁',
    `store_id`=17, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在曹杨路附近做公司法务，计划长住一到两年；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=57;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=36, `age_required`='必须',
    `budget_min`=4000, `budget_max`=5800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=57;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-08-20', `rent_budget`=4800, `tidiness`='整洁',
    `store_id`=17, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在曹杨路附近做公司法务，计划长住一到两年；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=60;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=36, `age_required`='必须',
    `budget_min`=4000, `budget_max`=5800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=60;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-08-20', `rent_budget`=4800, `tidiness`='整洁',
    `store_id`=17, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在曹杨路附近做公司法务，计划长住一到两年；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=61;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=36, `age_required`='必须',
    `budget_min`=4000, `budget_max`=5800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=61;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-08-20', `rent_budget`=4800, `tidiness`='整洁',
    `store_id`=17, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在曹杨路附近做公司法务，计划长住一到两年；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=62;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=36, `age_required`='必须',
    `budget_min`=4000, `budget_max`=5800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=62;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-08-20', `rent_budget`=4800, `tidiness`='整洁',
    `store_id`=17, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在曹杨路附近做公司法务，计划长住一到两年；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=65;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=36, `age_required`='必须',
    `budget_min`=4000, `budget_max`=5800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=65;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-08-20', `rent_budget`=4800, `tidiness`='整洁',
    `store_id`=17, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在曹杨路附近做公司法务，计划长住一到两年；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=70;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=36, `age_required`='必须',
    `budget_min`=4000, `budget_max`=5800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=70;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2003-01-15', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=14, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在莘庄附近做绘图员，预算比较紧，计划长住一年以上；作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=78;

UPDATE `roommate_preference`
SET `age_min`=21, `age_max`=29, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=78;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2003-01-15', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=14, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在莘庄附近做绘图员，预算比较紧，计划长住一年以上；作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=79;

UPDATE `roommate_preference`
SET `age_min`=21, `age_max`=29, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=79;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2003-01-15', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=14, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在莘庄附近做绘图员，预算比较紧，计划长住一年以上；作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=80;

UPDATE `roommate_preference`
SET `age_min`=21, `age_max`=29, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=80;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2003-01-15', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=14, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在莘庄附近做绘图员，预算比较紧，计划长住一年以上；作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=87;

UPDATE `roommate_preference`
SET `age_min`=21, `age_max`=29, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=87;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2003-01-15', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=14, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在莘庄附近做绘图员，预算比较紧，计划长住一年以上；作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=88;

UPDATE `roommate_preference`
SET `age_min`=21, `age_max`=29, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=88;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2003-01-15', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=14, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在莘庄附近做绘图员，预算比较紧，计划长住一年以上；作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=89;

UPDATE `roommate_preference`
SET `age_min`=21, `age_max`=29, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=89;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2003-01-15', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=14, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在莘庄附近做绘图员，预算比较紧，计划长住一年以上；作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=93;

UPDATE `roommate_preference`
SET `age_min`=21, `age_max`=29, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=93;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2003-01-15', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=14, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在莘庄附近做绘图员，预算比较紧，计划长住一年以上；作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=94;

UPDATE `roommate_preference`
SET `age_min`=21, `age_max`=29, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=94;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-10-10', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=9, `schedule_type`='夜猫子', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山公园附近做摄影师，晚上修片到一两点，早上起得晚。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=95;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=95;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-10-10', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=9, `schedule_type`='夜猫子', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山公园附近做摄影师，晚上修片到一两点，早上起得晚。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=96;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=96;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-10-10', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=9, `schedule_type`='夜猫子', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山公园附近做摄影师，晚上修片到一两点，早上起得晚。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=104;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=104;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-10-10', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=9, `schedule_type`='夜猫子', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山公园附近做摄影师，晚上修片到一两点，早上起得晚。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=105;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=105;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-10-10', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=9, `schedule_type`='夜猫子', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山公园附近做摄影师，晚上修片到一两点，早上起得晚。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=106;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=106;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-10-10', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=9, `schedule_type`='夜猫子', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山公园附近做摄影师，晚上修片到一两点，早上起得晚。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=109;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=109;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-10-10', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=9, `schedule_type`='夜猫子', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山公园附近做摄影师，晚上修片到一两点，早上起得晚。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=111;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=111;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-10-10', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=9, `schedule_type`='夜猫子', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山公园附近做摄影师，晚上修片到一两点，早上起得晚。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=112;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=112;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1992-11-01', `rent_budget`=3000, `tidiness`='一般',
    `store_id`=6, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在五角场附近做工程师，计划先住三到六个月；作息正常，能接受猫。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=115;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=115;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1992-11-01', `rent_budget`=3000, `tidiness`='一般',
    `store_id`=6, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在五角场附近做工程师，计划先住三到六个月；作息正常，能接受猫。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=116;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=116;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1992-11-01', `rent_budget`=3000, `tidiness`='一般',
    `store_id`=6, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在五角场附近做工程师，计划先住三到六个月；作息正常，能接受猫。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=119;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=119;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1992-11-01', `rent_budget`=3000, `tidiness`='一般',
    `store_id`=6, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在五角场附近做工程师，计划先住三到六个月；作息正常，能接受猫。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=120;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=120;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1992-11-01', `rent_budget`=3000, `tidiness`='一般',
    `store_id`=6, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在五角场附近做工程师，计划先住三到六个月；作息正常，能接受猫。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=123;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=123;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1992-11-01', `rent_budget`=3000, `tidiness`='一般',
    `store_id`=6, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在五角场附近做工程师，计划先住三到六个月；作息正常，能接受猫。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=124;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=124;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1992-11-01', `rent_budget`=3000, `tidiness`='一般',
    `store_id`=6, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在五角场附近做工程师，计划先住三到六个月；作息正常，能接受猫。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=125;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=125;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1992-11-01', `rent_budget`=3000, `tidiness`='一般',
    `store_id`=6, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在五角场附近做工程师，计划先住三到六个月；作息正常，能接受猫。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=126;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=2500, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=126;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-07-07', `rent_budget`=3500, `tidiness`='一般',
    `store_id`=11, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在龙华附近做设计，计划先住两三个月；偶尔在楼下抽烟，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=71;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=71;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-07-07', `rent_budget`=3500, `tidiness`='一般',
    `store_id`=11, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在龙华附近做设计，计划先住两三个月；偶尔在楼下抽烟，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=73;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=73;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-07-07', `rent_budget`=3500, `tidiness`='一般',
    `store_id`=11, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在龙华附近做设计，计划先住两三个月；偶尔在楼下抽烟，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=74;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=74;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-07-07', `rent_budget`=3500, `tidiness`='一般',
    `store_id`=11, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在龙华附近做设计，计划先住两三个月；偶尔在楼下抽烟，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=75;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=75;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-07-07', `rent_budget`=3500, `tidiness`='一般',
    `store_id`=11, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在龙华附近做设计，计划先住两三个月；偶尔在楼下抽烟，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=76;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=76;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-07-07', `rent_budget`=3500, `tidiness`='一般',
    `store_id`=11, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在龙华附近做设计，计划先住两三个月；偶尔在楼下抽烟，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=77;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=77;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-07-07', `rent_budget`=3500, `tidiness`='一般',
    `store_id`=11, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在龙华附近做设计，计划先住两三个月；偶尔在楼下抽烟，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=81;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=81;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-07-07', `rent_budget`=3500, `tidiness`='一般',
    `store_id`=11, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在龙华附近做设计，计划先住两三个月；偶尔在楼下抽烟，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=149;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=149;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-04-18', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=7, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在静安寺附近做医生，工作稳定，计划长住两年以上；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=150;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=150;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-04-18', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=7, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在静安寺附近做医生，工作稳定，计划长住两年以上；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=156;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=156;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-04-18', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=7, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在静安寺附近做医生，工作稳定，计划长住两年以上；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=157;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=157;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-04-18', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=7, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在静安寺附近做医生，工作稳定，计划长住两年以上；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=159;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=159;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-04-18', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=7, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在静安寺附近做医生，工作稳定，计划长住两年以上；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=163;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=163;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-04-18', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=7, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在静安寺附近做医生，工作稳定，计划长住两年以上；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=166;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=166;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-04-18', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=7, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在静安寺附近做医生，工作稳定，计划长住两年以上；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=167;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=167;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-04-18', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=7, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在静安寺附近做医生，工作稳定，计划长住两年以上；作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，预算和租期对得上；不介意猫的话更好。'
WHERE `id`=169;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,正常作息', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=169;

