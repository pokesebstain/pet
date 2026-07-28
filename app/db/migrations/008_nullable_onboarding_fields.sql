-- 迁移 008：企业微信客户自动建档支持——放宽建档时非必需字段的 NOT NULL 约束
-- （对应设计 14.9 / Requirement 25：未识别到会员时，仅采集姓名 + 宠物名即可建档，
-- 手机号 / 宠物出生日期 / 体重留空、到店由店员核实补全，避免臆造占位数据污染
-- 下游健康分析 / 生命阶段判断等引擎）。
--
-- customers.phone：企业微信自动建档场景下客户可能未提供手机号。
-- pets.birth_date / pets.weight_kg：自动建档场景下通常无法获知，留空更安全
-- （下游引擎需按 IS NULL 跳过而非用占位值参与计算，见 app/engines/lifestage.py /
-- app/engines/health.py 的相应判空逻辑）。
--
-- 使用 IF EXISTS / 条件放宽以保证幂等，可重复执行。

ALTER TABLE customers ALTER COLUMN phone DROP NOT NULL;
ALTER TABLE pets ALTER COLUMN birth_date DROP NOT NULL;
ALTER TABLE pets ALTER COLUMN weight_kg DROP NOT NULL;

-- 新增标记列：区分"客户自主完整登记"与"企业微信自动建档待完善"，供门店后台提示
-- 店员核实补全（不影响 RLS / 现有查询，缺省为 FALSE 兼容既有数据）。
ALTER TABLE customers ADD COLUMN IF NOT EXISTS onboarding_pending BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS onboarding_pending BOOLEAN NOT NULL DEFAULT FALSE;

-- 宠物名（此前 schema 遗漏）：企业微信客户对宠物的称呼（如"绒绒"），用于门店人工核对
-- 与后续对话中指代宠物；自动建档场景下必填（否则店员无法从系统中识别是哪只宠物）。
-- 对既有数据留空（历史宠物档案可能确无登记名字），不追溯补全。
ALTER TABLE pets ADD COLUMN IF NOT EXISTS name TEXT;
