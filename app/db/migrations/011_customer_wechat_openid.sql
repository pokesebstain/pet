-- Migration 011: add wechat_openid column to customers table.
-- Used to bind manually-created customers with WeChat public account users.
-- After binding, public account messages can identify the customer via openid.

ALTER TABLE customers ADD COLUMN IF NOT EXISTS wechat_openid TEXT;

-- Index for tenant-scoped lookup by public account openid (RLS still applies).
CREATE INDEX IF NOT EXISTS ix_customers_wechat_openid
    ON customers (wechat_openid);
