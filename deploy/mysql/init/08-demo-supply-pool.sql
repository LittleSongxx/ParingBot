-- 演示数据：补齐长租/低预算/远门店供给，让场景矩阵的弱场景有可匹配候选。
-- 只更新未出现在历史 task 40/78 候选池里的演示档案；不改 user 表。
SET NAMES utf8mb4;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=856;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=856;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=857;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=857;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=859;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=859;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=864;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=864;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=865;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=865;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=866;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=866;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=867;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=867;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=871;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=871;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=872;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=872;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=879;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=879;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=881;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=881;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=882;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=882;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=885;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=885;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=887;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=887;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=890;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=890;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1995-06-15', `rent_budget`=3200, `tidiness`='整洁',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划长租，预算稳定，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=894;

UPDATE `roommate_preference`
SET `age_min`=26, `age_max`=36, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=894;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-03-10', `rent_budget`=3300, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划住一年左右，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=771;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=771;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-03-10', `rent_budget`=3300, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划住一年左右，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=772;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=772;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-03-10', `rent_budget`=3300, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划住一年左右，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=773;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=773;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-03-10', `rent_budget`=3300, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划住一年左右，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=776;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=776;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-03-10', `rent_budget`=3300, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划住一年左右，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=777;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=777;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-03-10', `rent_budget`=3300, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划住一年左右，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=778;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=778;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-03-10', `rent_budget`=3300, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划住一年左右，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=780;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=780;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-03-10', `rent_budget`=3300, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在附近上班，作息正常、不吸烟；计划住一年左右，想找同门店室友。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=781;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=781;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-04-12', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在张江附近上班，作息正常、不吸烟；预算不高，计划先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=3;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=2800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=3;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-04-12', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在张江附近上班，作息正常、不吸烟；预算不高，计划先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=7;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=2800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=7;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-04-12', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在张江附近上班，作息正常、不吸烟；预算不高，计划先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=10;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=2800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=10;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-04-12', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在张江附近上班，作息正常、不吸烟；预算不高，计划先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=14;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=2800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=14;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-04-12', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在张江附近上班，作息正常、不吸烟；预算不高，计划先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=16;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=2800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=16;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-04-12', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在张江附近上班，作息正常、不吸烟；预算不高，计划先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=23;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=2800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=23;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-04-12', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在张江附近上班，作息正常、不吸烟；预算不高，计划先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=26;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=2800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=26;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-04-12', `rent_budget`=2600, `tidiness`='一般',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在张江附近上班，作息正常、不吸烟；预算不高，计划先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=27;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2500, `budget_max`=2800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=27;

