-- Agent 加固：首轮检索的加分项预算。
-- 背景：真实场景矩阵里，首轮把 6 个加分项一次全用，候选池只剩 1 人，
-- 之后 10 轮放宽都在同一范围内打转；这里把规则写进提示词和工具说明。
SET NAMES utf8mb4;

UPDATE `prompt_template`
SET `content` = REPLACE(`content`,
  '2. search_members 每轮最多调用 2 次：第二次只能用于修正第一次的参数错误；返回 total=0 时不要连续换条件穷举，按放宽规则处理或直接给出本轮结论。',
  '2. search_members 每轮最多调用 2 次：第二次只能用于修正第一次的参数错误；返回 total=0 时不要连续换条件穷举，按放宽规则处理或直接给出本轮结论。首轮检索最多同时使用 2 个加分项（可选项全用等于把加分项变成硬条件）；其余加分项留到后续放宽轮次逐项使用。')
WHERE `code` = 'SCREENER_PROMPT'
  AND `content` NOT LIKE '%首轮检索最多同时使用 2 个加分项%';

UPDATE `function_tool`
SET `description` = CONCAT(`description`, ' 首轮检索最多同时使用 2 个加分项；可选项全用会把加分项变成硬条件。')
WHERE `tool_code` = 'search_members'
  AND `description` NOT LIKE '%首轮检索最多同时使用 2 个加分项%';
