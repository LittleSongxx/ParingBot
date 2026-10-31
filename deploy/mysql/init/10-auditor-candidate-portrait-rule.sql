-- 审核官：候选没有画像 ≠ 不合适。
-- 真实场景矩阵 S7 复现：8 位硬条件全满足的候选因为没有画像，被审核官
-- 连续以 PORTRAIT_INSUFFICIENT 否决，整次运行 0 交付。候选的档案、自我介绍、
-- 动态本身也是依据；只有这些都缺失/不足时才允许判 PORTRAIT_INSUFFICIENT。
SET NAMES utf8mb4;

UPDATE `prompt_template`
SET `content` = REPLACE(`content`,
  '4. 申请方档案或画像不足以判断时，判否决并把原因分类写成 PORTRAIT_INSUFFICIENT，同时说清缺哪个维度。',
  '4. 申请方档案或画像不足以判断时，判否决并把原因分类写成 PORTRAIT_INSUFFICIENT，同时说清缺哪个维度。候选没有画像不等于不合适：先用候选的档案、自我介绍、动态评估；只有这些也缺失或不足以判断时，才判 PORTRAIT_INSUFFICIENT，不能仅因没有画像判否决。')
WHERE `code` = 'AUDITOR_PROMPT'
  AND `content` NOT LIKE '%候选没有画像不等于不合适%';
