-- Agent 工具调用加固：把真实评测里暴露的模型工具误用写进提示词与工具描述。
-- 触发原因（deepseek-flash 真实运行）：门店范围缺 store_id、同一工具连续调用、
-- 一轮放宽多个维度、放宽说明缺幅度数字。这里是提示词/工具说明层加固，不改业务规则。
-- 放在 04 之后执行；只在这些提示词尚未包含加固块时追加，可重复执行。
SET NAMES utf8mb4;

UPDATE `prompt_template`
SET `content` = REPLACE(`content`, '【安全约束】', '【工具调用纪律】（以下规则代码会按实际参数校验，违反会被拒绝）
1. 开始先调用一次 read_roommate_preference；返回里没有 store_id，门店编码不要猜，search_members 会自动使用申请方档案里的意向门店。
2. search_members 每轮最多调用 2 次：第二次只能用于修正第一次的参数错误；返回 total=0 时不要连续换条件穷举，按放宽规则处理或直接给出本轮结论。
3. 门店范围是「同门店」或「同片区」时，store_scope 照偏好传；store_id 可以不传，代码默认用申请方自己的门店；不要编造门店编码。
4. save_candidates 的 found_round 用当前调度轮次；relax_note 只写一个维度，格式必须是以下之一：预算上限+200、年龄上限+2、门店+1级、整洁度+1档、租期+1档、作息+1级；没有放宽必须填空字符串。
5. 工具返回错误时按提示只改一处后重试一次，不要原样重复同一个调用；不要连续调用同一个工具超过 2 次。
6. 示例（数字仅示意，不要照抄）：
search_members：{"gender":"男","store_scope":"同门店","age_min":24,"age_max":32,"budget_min":2500,"budget_max":4000,"tidiness_min":"整洁","schedule_accept":"早睡早起,正常作息","lease_min":"6-12个月"}
save_candidates：{"candidates":[{"candidate_member_id":101,"screen_score":82}],"found_round":2,"relax_note":"预算上限+200"}
没有放宽时：{"candidates":[],"found_round":2,"relax_note":""}

【安全约束】')
WHERE `code` = 'SCREENER_PROMPT'
  AND `content` NOT LIKE '%工具调用纪律%';

UPDATE `prompt_template`
SET `content` = REPLACE(`content`, '【安全约束】', '6. 如果上一轮某个角色被闸拦下（结论里出现「被闸拦下」「工具调用次数已经用满」「同一个工具连续调用」），不要原样再派同一个角色；换另一个角色或直接收尾。同一角色连续被拦两次时直接收尾。

【安全约束】')
WHERE `code` = 'SUPERVISOR_PROMPT'
  AND `content` NOT LIKE '%被闸拦下%';

UPDATE `function_tool`
SET `description` = '按条件检索候选租客，只返回档案已通过审核且不是申请方本人的租客，单次最多返回 30 条，结果里带 total、returned、hasMore 三个数字。硬筛先调一次；不要用它穷举翻页，候选不够应当通过放宽加分项来解决。未提供的条件表示不限制。门店范围不是「不限」时，store_id 可以不传，代码默认使用申请方自己的意向门店；不要自己猜或编造门店编码。'
WHERE `tool_code` = 'search_members';

UPDATE `function_tool`
SET `input_schema` = REPLACE(`input_schema`, '申请方的意向门店编码，1 到 20，门店范围不是不限时必传', '可选；门店范围不是不限时，不传默认使用申请方自己的门店编码')
WHERE `tool_code` = 'search_members';

UPDATE `function_tool`
SET `description` = '把本轮筛出的候选一次性写入候选池，必须带上是第几轮筛出来的；放宽了条件时必须填 relax_note，且一轮只能放宽一个维度，格式为「预算上限+200」「年龄上限+2」「门店+1级」「整洁度+1档」「租期+1档」「作息+1级」之一；本次没放宽时 relax_note 填空字符串。代码会校验只能放宽标为加分的维度、每一轮只放宽一个维度、放宽幅度不越界，越界直接拒绝并把原因返回。本轮没筛到候选时也要调用一次，把放宽说明或结论带回来。'
WHERE `tool_code` = 'save_candidates';
