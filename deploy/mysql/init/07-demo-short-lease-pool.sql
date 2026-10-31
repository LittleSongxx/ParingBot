-- 演示数据：补充短租候选，让「3个月以下/3-6个月」的租客也能在演示库里匹配到人。
-- 这些档案只用于演示；不碰历史 task 40/78 的候选池（那两批候选人不在本名单里）。
-- 计划租期档位差 <2 才允许合租；这里补 10 位女性候选，属性对齐演示租客禾瑾的偏好。
SET NAMES utf8mb4;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-15', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=32;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=32;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-07-20', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=231;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=231;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-15', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=403;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=403;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-07-20', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=458;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=458;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-15', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=467;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=467;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-07-20', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3个月以下', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=641;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=641;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-15', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=719;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=719;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-07-20', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=788;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=788;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='2000-01-15', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=817;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=817;

UPDATE `member_profile`
SET `gender`='女', `birth_date`='1999-07-20', `rent_budget`=4000, `tidiness`='整洁',
    `store_id`=1, `schedule_type`='正常作息', `lease_term`='3-6个月', `has_pet`='无',
    `smoking`='不吸烟', `audit_status`='已通过', `enabled`='是',
    `self_intro`='在浦东上班，作息正常、不吸烟；近期是过渡期，计划先住两三个月。', `roommate_expectation`='希望室友作息规律、爱干净，尽量同门店通勤，不在屋里抽烟。'
WHERE `id`=861;

UPDATE `roommate_preference`
SET `age_min`=23, `age_max`=30, `age_required`='必须',
    `budget_min`=3200, `budget_max`=5000, `budget_required`='加分',
    `tidiness_min`='整洁', `tidiness_required`='加分',
    `store_scope`='同门店', `store_required`='加分',
    `schedule_accept`='早睡早起,正常作息', `schedule_required`='必须',
    `lease_min`='3个月以下', `lease_required`='加分',
    `pet_accept`='无所谓', `pet_required`='加分'
WHERE `member_id`=861;
