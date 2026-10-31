-- 演示数据：为扩展场景 S13/S15/S16/S18/S20 补齐可匹配候选（避开已有短租/弱场景供给）。
-- 这些是演示供给，不是业务规则；历史 task 40/78 候选不在此名单。
SET NAMES utf8mb4;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2001-03-10', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=2, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='刚毕业做助理工程师，预算有限，先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=20;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=20;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2001-03-10', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=2, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='刚毕业做助理工程师，预算有限，先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=22;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=22;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2001-03-10', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=2, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='刚毕业做助理工程师，预算有限，先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=24;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=24;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2001-03-10', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=2, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='刚毕业做助理工程师，预算有限，先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=25;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=25;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2001-03-10', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=2, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='刚毕业做助理工程师，预算有限，先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=30;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=30;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2001-03-10', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=2, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='刚毕业做助理工程师，预算有限，先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=33;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=33;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2001-03-10', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=2, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='刚毕业做助理工程师，预算有限，先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=34;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=34;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='2001-03-10', `rent_budget`=2800, `tidiness`='一般',
    `store_id`=2, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='刚毕业做助理工程师，预算有限，先住三到六个月。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=35;

UPDATE `roommate_preference`
SET `age_min`=22, `age_max`=30, `age_required`='必须',
    `budget_min`=2200, `budget_max`=3200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=35;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1993-10-08', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=8, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在松江做建筑，长住两年以上，养了一只安静的猫。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=82;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=82;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1993-10-08', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=8, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在松江做建筑，长住两年以上，养了一只安静的猫。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=83;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=83;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1993-10-08', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=8, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在松江做建筑，长住两年以上，养了一只安静的猫。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=84;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=84;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1993-10-08', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=8, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在松江做建筑，长住两年以上，养了一只安静的猫。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=85;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=85;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1993-10-08', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=8, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在松江做建筑，长住两年以上，养了一只安静的猫。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=86;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=86;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1993-10-08', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=8, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在松江做建筑，长住两年以上，养了一只安静的猫。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=90;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=90;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1993-10-08', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=8, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在松江做建筑，长住两年以上，养了一只安静的猫。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=97;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=97;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1993-10-08', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=8, `schedule_type`='正常作息', `lease_term`='2年以上', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在松江做建筑，长住两年以上，养了一只安静的猫。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=98;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=40, `age_required`='必须',
    `budget_min`=3500, `budget_max`=5200, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='2年以上', `lease_required`='加分',
    `pet_accept`='接受', `pet_required`='加分'
WHERE `member_id`=98;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-05-20', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做新媒体，晚上剪片子到一两点，作息偏夜猫子但很安静。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=99;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=33, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=99;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-05-20', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做新媒体，晚上剪片子到一两点，作息偏夜猫子但很安静。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=100;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=33, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=100;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-05-20', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做新媒体，晚上剪片子到一两点，作息偏夜猫子但很安静。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=101;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=33, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=101;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-05-20', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做新媒体，晚上剪片子到一两点，作息偏夜猫子但很安静。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=102;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=33, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=102;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-05-20', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做新媒体，晚上剪片子到一两点，作息偏夜猫子但很安静。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=103;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=33, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=103;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-05-20', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做新媒体，晚上剪片子到一两点，作息偏夜猫子但很安静。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=107;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=33, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=107;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-05-20', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做新媒体，晚上剪片子到一两点，作息偏夜猫子但很安静。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=108;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=33, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=108;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-05-20', `rent_budget`=4200, `tidiness`='一般',
    `store_id`=12, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做新媒体，晚上剪片子到一两点，作息偏夜猫子但很安静。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=110;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=33, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='夜猫子,正常作息', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=110;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-04-12', `rent_budget`=3200, `tidiness`='一般',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近做行政，希望走路通勤，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=113;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=2800, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=113;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-04-12', `rent_budget`=3200, `tidiness`='一般',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近做行政，希望走路通勤，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=114;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=2800, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=114;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-04-12', `rent_budget`=3200, `tidiness`='一般',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近做行政，希望走路通勤，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=118;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=2800, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=118;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-04-12', `rent_budget`=3200, `tidiness`='一般',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近做行政，希望走路通勤，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=122;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=2800, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=122;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-04-12', `rent_budget`=3200, `tidiness`='一般',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近做行政，希望走路通勤，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=127;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=2800, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=127;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-04-12', `rent_budget`=3200, `tidiness`='一般',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近做行政，希望走路通勤，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=128;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=2800, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=128;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-04-12', `rent_budget`=3200, `tidiness`='一般',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近做行政，希望走路通勤，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=130;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=2800, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=130;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1997-04-12', `rent_budget`=3200, `tidiness`='一般',
    `store_id`=20, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在中山北路附近做行政，希望走路通勤，作息正常。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=132;

UPDATE `roommate_preference`
SET `age_min`=24, `age_max`=34, `age_required`='必须',
    `budget_min`=2800, `budget_max`=3800, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=132;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-11-01', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在紫竹做研究员，项目三到六个月，作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=133;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=32, `age_required`='必须',
    `budget_min`=3500, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=133;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-11-01', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在紫竹做研究员，项目三到六个月，作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=134;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=32, `age_required`='必须',
    `budget_min`=3500, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=134;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-11-01', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在紫竹做研究员，项目三到六个月，作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=138;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=32, `age_required`='必须',
    `budget_min`=3500, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=138;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-11-01', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在紫竹做研究员，项目三到六个月，作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=139;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=32, `age_required`='必须',
    `budget_min`=3500, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=139;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-11-01', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在紫竹做研究员，项目三到六个月，作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=142;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=32, `age_required`='必须',
    `budget_min`=3500, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=142;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-11-01', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在紫竹做研究员，项目三到六个月，作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=143;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=32, `age_required`='必须',
    `budget_min`=3500, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=143;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-11-01', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在紫竹做研究员，项目三到六个月，作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=144;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=32, `age_required`='必须',
    `budget_min`=3500, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=144;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1995-11-01', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=10, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在紫竹做研究员，项目三到六个月，作息规律、爱干净。', `roommate_expectation`='希望室友作息规律、爱干净，租期和预算对得上。'
WHERE `id`=148;

UPDATE `roommate_preference`
SET `age_min`=28, `age_max`=32, `age_required`='必须',
    `budget_min`=3500, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='一般', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息', `schedule_required`='加分',
    `lease_min`='3-6个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=148;

