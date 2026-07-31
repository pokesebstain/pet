-- 迁移 011：客户公众号 openid 绑定列。
-- 用于将后台手动建的客户与微信公众号进来的用户进行绑定。
-- 绑定后，公众号用户发送消息可通过 openid 识别对应客户。

ALTER TABLE customers ADD COLUMN IF NOT EXISTS wechat_openid TEXT;

-- 便于按公众号 openid 做租户内查找（RLS 仍将结果限定在当前租户）。
CREATE INDEX IF NOT EXISTS ix_customers_wechat_openid
    ON customers (wechat_openid);
