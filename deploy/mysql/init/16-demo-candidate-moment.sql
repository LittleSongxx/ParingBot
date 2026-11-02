-- 演示数据：候选 743 的动态只对匹配室友可见，画像师只读公开动态，导致一直生成不了画像。
-- 补一条公开动态，让评测集最后一位交付候选也能生成画像。
SET NAMES utf8mb4;

INSERT INTO `member_moment` (`member_id`, `content`, `visible`, `publish_time`, `create_time`, `update_time`)
SELECT 743,
       '最近在整理搬家的东西，计划在这边稳定住一到两年；平时喜欢看纪录片、喝茶。',
       '公开', NOW(), NOW(), NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM `member_moment` WHERE `member_id` = 743 AND `visible` = '公开'
);
