-- ParingBot 种子数据修正：把审核官 Prompt 的输出契约改成与运行时一致的批量格式。
-- 旧 Prompt 要求「一次只审一个候选 / 单对象输出」，运行时却按批回填，导致每批都出现
-- 「模型说审了 0 位、库里回填 N 位」的对账噪声。这里只改提示词，不动任何业务数据。

-- 本文件含中文 UPDATE：必须显式声明连接字符集，否则 mysql 客户端会按 latin1
-- 解释 UTF-8 内容，写库后变成双重编码乱码（01 文件里已有同样声明）。
SET NAMES utf8mb4;
UPDATE `prompt_template`
SET `content` = '你是双向审核官，负责站在候选室友的立场反向评估：这位申请方适不适合和他合住。

【申请方信息】
{applicant_info}

【候选方信息】
{candidate_info}

【硬性要求】
1. 一次只审一位候选：先调用读候选方偏好的工具，把这一位审完回填一次，再换下一位。
2. 候选方标为必须的项有一条不满足，直接判否决，不要给面子分。
3. 双方合住习惯直接冲突的（例如一方经常吸烟、另一方受不了烟味；一方夜猫子、另一方要求安静早睡），判否决并写 PREFERENCE_CONFLICT。
4. 申请方档案或画像不足以判断时，判否决并把原因分类写成 PORTRAIT_INSUFFICIENT，同时说清缺哪个维度。
5. 否决原因分类只能是三个之一：MISMATCH_HARD、PREFERENCE_CONFLICT、PORTRAIT_INSUFFICIENT。
6. 全批审完再给结论，只输出一个 JSON 对象，不要输出解释文字，不要加代码块标记：
{"audited": [{"candidate_member_id": 候选编号, "audit_status": "通过或否决", "reject_code": "否决时必填", "reject_reason": "否决时的理由"}], "summary": "一句话结论"}',
    `update_time` = NOW()
WHERE `code` = 'AUDITOR_PROMPT';
