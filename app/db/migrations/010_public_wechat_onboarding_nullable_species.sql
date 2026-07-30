-- 迁移 010：公众号渐进式建档允许宠物物种 / 品种在后续对话补齐。
-- Requirement 26.5 明确禁止将缺失资料伪造成事实性 "unknown"；保留 NULL 并以
-- onboarding_pending 标记待完善档案，避免污染生命阶段、健康与推荐逻辑。

ALTER TABLE pets ALTER COLUMN species DROP NOT NULL;
ALTER TABLE pets ALTER COLUMN breed DROP NOT NULL;
