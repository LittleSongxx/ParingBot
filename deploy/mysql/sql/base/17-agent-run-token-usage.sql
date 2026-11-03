-- 评测/成本观测：记录每次运行的模型 token 用量（各模型调用累加）。
SET NAMES utf8mb4;

ALTER TABLE `agent_run`
    ADD COLUMN `prompt_tokens` INT NOT NULL DEFAULT 0 COMMENT '输入 token 累计',
    ADD COLUMN `completion_tokens` INT NOT NULL DEFAULT 0 COMMENT '输出 token 累计';
