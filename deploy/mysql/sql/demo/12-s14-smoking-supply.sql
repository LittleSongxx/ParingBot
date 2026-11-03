-- 演示数据：S14 短租+偶尔吸烟 场景补候选。
-- 仅补演示供给，不改业务规则；历史 task 40/78 候选不在名单。
SET NAMES utf8mb4;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-06-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=3, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在唐镇附近上班，做销售，计划短租三到六个月。作息正常、爱干净；不介意室友偶尔在楼下抽烟。',
    `roommate_expectation`='希望室友作息正常、爱干净；抽烟的话尽量在楼下，不在屋里抽。'
WHERE `id`=5;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=5;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-06-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=3, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在唐镇附近上班，做销售，计划短租三到六个月。作息正常、爱干净；不介意室友偶尔在楼下抽烟。',
    `roommate_expectation`='希望室友作息正常、爱干净；抽烟的话尽量在楼下，不在屋里抽。'
WHERE `id`=6;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=6;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-06-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=3, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在唐镇附近上班，做销售，计划短租三到六个月。作息正常、爱干净；不介意室友偶尔在楼下抽烟。',
    `roommate_expectation`='希望室友作息正常、爱干净；抽烟的话尽量在楼下，不在屋里抽。'
WHERE `id`=8;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=8;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-06-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=3, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在唐镇附近上班，做销售，计划短租三到六个月。作息正常、爱干净；不介意室友偶尔在楼下抽烟。',
    `roommate_expectation`='希望室友作息正常、爱干净；抽烟的话尽量在楼下，不在屋里抽。'
WHERE `id`=9;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=9;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-06-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=3, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在唐镇附近上班，做销售，计划短租三到六个月。作息正常、爱干净；不介意室友偶尔在楼下抽烟。',
    `roommate_expectation`='希望室友作息正常、爱干净；抽烟的话尽量在楼下，不在屋里抽。'
WHERE `id`=15;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=15;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-06-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=3, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在唐镇附近上班，做销售，计划短租三到六个月。作息正常、爱干净；不介意室友偶尔在楼下抽烟。',
    `roommate_expectation`='希望室友作息正常、爱干净；抽烟的话尽量在楼下，不在屋里抽。'
WHERE `id`=17;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=17;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-06-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=3, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在唐镇附近上班，做销售，计划短租三到六个月。作息正常、爱干净；不介意室友偶尔在楼下抽烟。',
    `roommate_expectation`='希望室友作息正常、爱干净；抽烟的话尽量在楼下，不在屋里抽。'
WHERE `id`=18;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=18;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1996-06-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=3, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在唐镇附近上班，做销售，计划短租三到六个月。作息正常、爱干净；不介意室友偶尔在楼下抽烟。',
    `roommate_expectation`='希望室友作息正常、爱干净；抽烟的话尽量在楼下，不在屋里抽。'
WHERE `id`=19;

UPDATE `roommate_preference`
SET `age_min`=25, `age_max`=35, `age_required`='必须',
    `budget_min`=2800, `budget_max`=4500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=19;

