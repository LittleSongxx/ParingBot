-- 演示数据：为 S12(35岁长租) / S17(40岁高预算) 补齐候选。
-- 避开已有 07/08/11/12 供给名单；不改业务规则。
SET NAMES utf8mb4;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-08-15', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=5, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在商城店附近做财务，工作稳定、计划长租一到两年；作息规律、爱干净，不吸烟。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=28;

UPDATE `roommate_preference`
SET `age_min`=30, `age_max`=40, `age_required`='必须',
    `budget_min`=3000, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=28;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-08-15', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=5, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在商城店附近做财务，工作稳定、计划长租一到两年；作息规律、爱干净，不吸烟。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=29;

UPDATE `roommate_preference`
SET `age_min`=30, `age_max`=40, `age_required`='必须',
    `budget_min`=3000, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=29;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-08-15', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=5, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在商城店附近做财务，工作稳定、计划长租一到两年；作息规律、爱干净，不吸烟。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=31;

UPDATE `roommate_preference`
SET `age_min`=30, `age_max`=40, `age_required`='必须',
    `budget_min`=3000, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=31;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-08-15', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=5, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在商城店附近做财务，工作稳定、计划长租一到两年；作息规律、爱干净，不吸烟。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=36;

UPDATE `roommate_preference`
SET `age_min`=30, `age_max`=40, `age_required`='必须',
    `budget_min`=3000, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=36;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-08-15', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=5, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在商城店附近做财务，工作稳定、计划长租一到两年；作息规律、爱干净，不吸烟。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=37;

UPDATE `roommate_preference`
SET `age_min`=30, `age_max`=40, `age_required`='必须',
    `budget_min`=3000, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=37;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-08-15', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=5, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在商城店附近做财务，工作稳定、计划长租一到两年；作息规律、爱干净，不吸烟。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=38;

UPDATE `roommate_preference`
SET `age_min`=30, `age_max`=40, `age_required`='必须',
    `budget_min`=3000, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=38;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-08-15', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=5, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在商城店附近做财务，工作稳定、计划长租一到两年；作息规律、爱干净，不吸烟。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=43;

UPDATE `roommate_preference`
SET `age_min`=30, `age_max`=40, `age_required`='必须',
    `budget_min`=3000, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=43;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1988-08-15', `rent_budget`=4200, `tidiness`='整洁',
    `store_id`=5, `schedule_type`='正常作息', `lease_term`='1-2年', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在商城店附近做财务，工作稳定、计划长租一到两年；作息规律、爱干净，不吸烟。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=44;

UPDATE `roommate_preference`
SET `age_min`=30, `age_max`=40, `age_required`='必须',
    `budget_min`=3000, `budget_max`=5000, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='1-2年', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=44;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1984-06-20', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做企业顾问，收入稳定、预算充足；作息正常、爱干净，不吸烟、不养宠物。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=39;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=39;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1984-06-20', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做企业顾问，收入稳定、预算充足；作息正常、爱干净，不吸烟、不养宠物。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=41;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=41;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1984-06-20', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做企业顾问，收入稳定、预算充足；作息正常、爱干净，不吸烟、不养宠物。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=42;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=42;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1984-06-20', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做企业顾问，收入稳定、预算充足；作息正常、爱干净，不吸烟、不养宠物。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=45;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=45;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1984-06-20', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做企业顾问，收入稳定、预算充足；作息正常、爱干净，不吸烟、不养宠物。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=48;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=48;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1984-06-20', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做企业顾问，收入稳定、预算充足；作息正常、爱干净，不吸烟、不养宠物。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=50;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=50;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1984-06-20', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做企业顾问，收入稳定、预算充足；作息正常、爱干净，不吸烟、不养宠物。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=51;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=51;

UPDATE `member_profile`
SET `gender`='男', `birth_date`='1984-06-20', `rent_budget`=5200, `tidiness`='整洁',
    `store_id`=18, `schedule_type`='正常作息', `lease_term`='6-12个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='做企业顾问，收入稳定、预算充足；作息正常、爱干净，不吸烟、不养宠物。', `roommate_expectation`='希望室友作息规律、爱干净，长租/预算稳定。'
WHERE `id`=52;

UPDATE `roommate_preference`
SET `age_min`=35, `age_max`=45, `age_required`='必须',
    `budget_min`=4500, `budget_max`=6500, `budget_required`='必须',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='必须',
    `schedule_accept`='正常作息,早睡早起', `schedule_required`='加分',
    `lease_min`='6-12个月', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=52;

