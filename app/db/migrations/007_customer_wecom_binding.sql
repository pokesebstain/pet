-- 迁移 007：客户企业微信外部联系人绑定列（对应设计 14.1 / 14.3 组件 A；任务 14 落地接线）。
--
-- 背景：企业微信入站消息携带 external_user_id（外部联系人标识，形如 "wmXXXX"）。为把该标识
-- 映射到平台 Customer，需要在 customers 上持久化一个可空的 wecom_external_id 绑定列。
-- 接待预约 Agent 的客户/宠物消解（DbCustomerPetResolver）据此解析下单客户：
--   1) 优先按 wecom_external_id 精确匹配；
--   2) 回退按 customer_id = external_user_id 的简单约定匹配（便于演示数据免绑定即可用）。
--
-- 该列可空、幂等新增（IF NOT EXISTS），不影响既有 RLS 策略（customers 的租户隔离策略在
-- 迁移 004 中已定义，基于会话变量 app.current_tenant），亦不改变既有列。

ALTER TABLE customers ADD COLUMN IF NOT EXISTS wecom_external_id TEXT;

-- 便于按外部联系人标识做租户内查找（RLS 仍将结果限定在当前租户）。
CREATE INDEX IF NOT EXISTS ix_customers_wecom_external_id
    ON customers (wecom_external_id);
