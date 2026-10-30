-- Phase 0「AI 辅助调用日志」表：资料教练、匹配解读官这类辅助能力每调用一次模型落一条，
-- 只存摘要（提示词与输入的 sha256、token 用量、耗时、状态），不存任何原文，
-- 给后续效果评估与排障留最小痕迹。
--
-- 归属：第 17 张业务表，和既有表一样按 id 逻辑关联，不建物理外键。
-- 索引：按「场景 + 时间」查最近调用，按 member_id 查某位租客的调用记录。
-- 本文件含中文 DDL 注释：必须显式声明连接字符集，避免 mysql 客户端按 latin1 解释 UTF-8。
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `ai_assist_log` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '日志ID',
  `scene` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '场景：profile_coach / match_brief 等',
  `member_id` int NULL DEFAULT NULL COMMENT '关联租客ID（可空）',
  `prompt_code` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '提示词模板编码',
  `prompt_hash` char(64) NULL DEFAULT NULL COMMENT '提示词全文 sha256（只存摘要，不存原文）',
  `model_name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '模型名称',
  `input_digest` char(64) NULL DEFAULT NULL COMMENT '输入载荷规范化 JSON 的 sha256（只存摘要，不存原文）',
  `latency_ms` int NULL DEFAULT NULL COMMENT '调用耗时（毫秒）',
  `prompt_tokens` int NULL DEFAULT NULL COMMENT '输入 token 数',
  `completion_tokens` int NULL DEFAULT NULL COMMENT '输出 token 数',
  `status` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '成功' COMMENT '调用状态：成功 / 失败',
  `adopted` tinyint(1) NOT NULL DEFAULT 0 COMMENT '结果是否被采纳：0 否 / 1 是',
  `error_message` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '失败原因（截断到 500 字）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录时间',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_ai_assist_log_scene_time`(`scene` ASC, `create_time` ASC) USING BTREE,
  INDEX `idx_ai_assist_log_member`(`member_id` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = 'AI辅助能力调用日志表' ROW_FORMAT = DYNAMIC;