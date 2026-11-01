-- 演示数据：为 S19(27岁宽偏好) 补 8 位候选。
-- 避开已有供给；不改业务规则。
SET NAMES utf8mb4;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=4, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在世纪大道附近做运营，计划长住一年以上；作息正常、爱干净，不吸烟、不养宠物。',
    `roommate_expectation`='希望室友正常人、好沟通，条件都可以商量。'
WHERE `id`=53;

UPDATE `roommate_preference`
SET `age_min`=18, `age_max`=60, `age_required`='必须',
    `budget_min`=800, `budget_max`=20000, `budget_required`='加分',
    `tidiness_min`='随意', `tidiness_required`='加分',
    `store_scope`='不限', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=53;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=4, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在世纪大道附近做运营，计划长住一年以上；作息正常、爱干净，不吸烟、不养宠物。',
    `roommate_expectation`='希望室友正常人、好沟通，条件都可以商量。'
WHERE `id`=55;

UPDATE `roommate_preference`
SET `age_min`=18, `age_max`=60, `age_required`='必须',
    `budget_min`=800, `budget_max`=20000, `budget_required`='加分',
    `tidiness_min`='随意', `tidiness_required`='加分',
    `store_scope`='不限', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=55;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=4, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在世纪大道附近做运营，计划长住一年以上；作息正常、爱干净，不吸烟、不养宠物。',
    `roommate_expectation`='希望室友正常人、好沟通，条件都可以商量。'
WHERE `id`=56;

UPDATE `roommate_preference`
SET `age_min`=18, `age_max`=60, `age_required`='必须',
    `budget_min`=800, `budget_max`=20000, `budget_required`='加分',
    `tidiness_min`='随意', `tidiness_required`='加分',
    `store_scope`='不限', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=56;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=4, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在世纪大道附近做运营，计划长住一年以上；作息正常、爱干净，不吸烟、不养宠物。',
    `roommate_expectation`='希望室友正常人、好沟通，条件都可以商量。'
WHERE `id`=59;

UPDATE `roommate_preference`
SET `age_min`=18, `age_max`=60, `age_required`='必须',
    `budget_min`=800, `budget_max`=20000, `budget_required`='加分',
    `tidiness_min`='随意', `tidiness_required`='加分',
    `store_scope`='不限', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=59;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=4, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在世纪大道附近做运营，计划长住一年以上；作息正常、爱干净，不吸烟、不养宠物。',
    `roommate_expectation`='希望室友正常人、好沟通，条件都可以商量。'
WHERE `id`=64;

UPDATE `roommate_preference`
SET `age_min`=18, `age_max`=60, `age_required`='必须',
    `budget_min`=800, `budget_max`=20000, `budget_required`='加分',
    `tidiness_min`='随意', `tidiness_required`='加分',
    `store_scope`='不限', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=64;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=4, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在世纪大道附近做运营，计划长住一年以上；作息正常、爱干净，不吸烟、不养宠物。',
    `roommate_expectation`='希望室友正常人、好沟通，条件都可以商量。'
WHERE `id`=67;

UPDATE `roommate_preference`
SET `age_min`=18, `age_max`=60, `age_required`='必须',
    `budget_min`=800, `budget_max`=20000, `budget_required`='加分',
    `tidiness_min`='随意', `tidiness_required`='加分',
    `store_scope`='不限', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=67;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=4, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在世纪大道附近做运营，计划长住一年以上；作息正常、爱干净，不吸烟、不养宠物。',
    `roommate_expectation`='希望室友正常人、好沟通，条件都可以商量。'
WHERE `id`=68;

UPDATE `roommate_preference`
SET `age_min`=18, `age_max`=60, `age_required`='必须',
    `budget_min`=800, `budget_max`=20000, `budget_required`='加分',
    `tidiness_min`='随意', `tidiness_required`='加分',
    `store_scope`='不限', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=68;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1998-09-18', `rent_budget`=3500, `tidiness`='整洁',
    `store_id`=4, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在世纪大道附近做运营，计划长住一年以上；作息正常、爱干净，不吸烟、不养宠物。',
    `roommate_expectation`='希望室友正常人、好沟通，条件都可以商量。'
WHERE `id`=69;

UPDATE `roommate_preference`
SET `age_min`=18, `age_max`=60, `age_required`='必须',
    `budget_min`=800, `budget_max`=20000, `budget_required`='加分',
    `tidiness_min`='随意', `tidiness_required`='加分',
    `store_scope`='不限', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息,夜猫子', `schedule_required`='加分',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=69;

