-- 吸烟是软冲突，不是一刀切硬否决。
-- S14 复现：申请方偶尔吸烟但只在楼下抽，候选方大多只是自己不吸烟；
-- 审核官有时判 PREFERENCE_CONFLICT，导致交付 7/8/8 波动。
SET NAMES utf8mb4;

UPDATE `prompt_template`
SET `content` = REPLACE(`content`,
  '3. 双方合住习惯直接冲突的（例如一方经常吸烟、另一方受不了烟味；一方夜猫子、另一方要求安静早睡），判否决并写 PREFERENCE_CONFLICT。',
  '3. 双方合住习惯直接冲突的（例如一方经常吸烟、另一方受不了烟味；一方夜猫子、另一方要求安静早睡），判否决并写 PREFERENCE_CONFLICT。吸烟是软冲突：申请方偶尔吸烟、且明确只在楼下/室外抽，候选方只是自己不吸烟、没有明确要求室友完全不抽烟时，可以判通过，但要在 summary 里提示租客线下确认；只有候选方明确要求室友不吸烟或不在屋里抽烟，且申请方经常吸烟/在屋里抽，才判 PREFERENCE_CONFLICT。')
WHERE `code` = 'AUDITOR_PROMPT'
  AND `content` NOT LIKE '%吸烟是软冲突%';
