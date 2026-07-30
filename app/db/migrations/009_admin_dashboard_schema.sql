-- 迁移 009：补齐 Admin Dashboard 后端（app/api/admin_routes.py）依赖的缺失列与缺失表。
--
-- 背景：Admin Dashboard 后端路由（任务：后端 11 资源 CRUD + Dashboard 聚合）编写时，
-- 部分 SQL 假设的表结构与既有迁移（002/006/008）实际创建的表结构不一致（多为"设计时
-- 假设了软删除 / 展示字段，但未同步写迁移"），线上暴露为多个端点 500（UndefinedColumn /
-- UndefinedTable）。本迁移补齐这些缺口；不影响既有业务表（排期引擎 / 健康分析引擎等）
-- 已在使用的列，仅新增。
--
-- 使用 IF NOT EXISTS / IF EXISTS 保证幂等，可重复执行。

-- --- customers：补软删除 + 客户运营（流失名单）展示字段 --------------------
-- deleted_at：Admin 后台"删除客户"为软删除（UPDATE deleted_at），而非物理删除，
-- 保留历史预约 / 订阅等外键引用的可追溯性。
ALTER TABLE customers ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- last_visit_at / total_visits：流失风险名单（/operations/churn）展示字段。
-- 缺省新客户为 NULL / 0；后续应由预约完成事件驱动更新（超出本次迁移范围，
-- 属于运营指标持续维护，暂不在此建触发器，避免引入未经验证的自动化写入逻辑）。
ALTER TABLE customers ADD COLUMN IF NOT EXISTS last_visit_at TIMESTAMPTZ;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS total_visits INTEGER NOT NULL DEFAULT 0;

-- --- business_hours：补"当日是否闭店"标记 ----------------------------------
ALTER TABLE business_hours ADD COLUMN IF NOT EXISTS is_closed BOOLEAN NOT NULL DEFAULT FALSE;

-- --- grooming_resources：补 Admin 资源页展示用的"单资源容量"字段 -------------
-- 注意：排期引擎（app/engines/scheduling_db.py）按服务类型 COUNT(*) 活跃资源行数
-- 作为该服务的总容量，从不读取本列；本列仅用于 Admin 后台展示 / 编辑单个资源的
-- 标称容量（如"该工位可同时容纳几只宠物"），与排期引擎的容量计算逻辑无关、不冲突。
ALTER TABLE grooming_resources ADD COLUMN IF NOT EXISTS capacity INTEGER NOT NULL DEFAULT 1;

-- --- skus：补 Admin 库存页展示 / 补货判断字段 -------------------------------
-- 注意：既有 category / unit_cost / lead_time_days 三列是排期无关的既有列，本迁移不动；
-- unit / reorder_point / safety_stock 是 Admin 库存页需要但从未补齐的字段。
ALTER TABLE skus ADD COLUMN IF NOT EXISTS unit TEXT NOT NULL DEFAULT '件';
ALTER TABLE skus ADD COLUMN IF NOT EXISTS reorder_point DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE skus ADD COLUMN IF NOT EXISTS safety_stock DOUBLE PRECISION NOT NULL DEFAULT 0;

-- --- subscriptions：补订阅开始时间 ------------------------------------------
-- 缺省回退 next_billing_at（无法追溯真实起始时间时，至少保证列非空、类型正确）。
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
UPDATE subscriptions SET started_at = next_billing_at WHERE started_at IS NULL;
ALTER TABLE subscriptions ALTER COLUMN started_at SET NOT NULL;

-- --- 新建表：health_alerts（健康预警，对应 app/agents/health.py 产出的预警事件） ---
CREATE TABLE IF NOT EXISTS health_alerts (
    alert_id   TEXT        PRIMARY KEY,
    tenant_id  TEXT        NOT NULL,
    pet_id     TEXT        NOT NULL,
    level      TEXT        NOT NULL,
    title      TEXT        NOT NULL,
    message    TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acked_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_health_alerts_tenant_id ON health_alerts (tenant_id);
CREATE INDEX IF NOT EXISTS ix_health_alerts_pet_id ON health_alerts (pet_id);

ALTER TABLE health_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE health_alerts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON health_alerts;
CREATE POLICY tenant_isolation ON health_alerts
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- --- 新建表：billing_records（订阅计费流水，供 Dashboard 营收统计 + 账单报表） ---
CREATE TABLE IF NOT EXISTS billing_records (
    record_id     TEXT           PRIMARY KEY,
    tenant_id     TEXT           NOT NULL,
    subscription_id TEXT,
    amount        NUMERIC(18, 2) NOT NULL,
    billing_month DATE           NOT NULL,
    status        TEXT           NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_billing_records_tenant_id ON billing_records (tenant_id);
CREATE INDEX IF NOT EXISTS ix_billing_records_billing_month ON billing_records (billing_month);

ALTER TABLE billing_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_records FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON billing_records;
CREATE POLICY tenant_isolation ON billing_records
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- --- 新建表：restock_decisions（补货决策，对应设计文档补货引擎产出） -----------
CREATE TABLE IF NOT EXISTS restock_decisions (
    decision_id     TEXT             PRIMARY KEY,
    tenant_id        TEXT             NOT NULL,
    sku_id           TEXT             NOT NULL,
    recommended_qty  DOUBLE PRECISION NOT NULL,
    urgency          TEXT             NOT NULL,
    status           TEXT             NOT NULL DEFAULT 'open',
    created_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_restock_decisions_tenant_id ON restock_decisions (tenant_id);
CREATE INDEX IF NOT EXISTS ix_restock_decisions_sku_id ON restock_decisions (sku_id);

ALTER TABLE restock_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE restock_decisions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON restock_decisions;
CREATE POLICY tenant_isolation ON restock_decisions
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- --- 新建表：marketing_contents（营销内容生成记录） ---------------------------
CREATE TABLE IF NOT EXISTS marketing_contents (
    content_id   TEXT        PRIMARY KEY,
    tenant_id    TEXT        NOT NULL,
    topic        TEXT        NOT NULL,
    channel      TEXT        NOT NULL,
    body_preview TEXT        NOT NULL DEFAULT '',
    status       TEXT        NOT NULL DEFAULT 'draft',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_marketing_contents_tenant_id ON marketing_contents (tenant_id);

ALTER TABLE marketing_contents ENABLE ROW LEVEL SECURITY;
ALTER TABLE marketing_contents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON marketing_contents;
CREATE POLICY tenant_isolation ON marketing_contents
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- --- 新建表：partner_hospitals（生态合作医院，平台级共享，非租户私有） ---------
-- 合作医院为平台级资源（不同门店可能共享同一合作医院），不设 tenant_id / RLS，
-- 与 knowledge_chunks 的"平台级共享"语义类似但更简单（无需租户可见性合并逻辑）。
CREATE TABLE IF NOT EXISTS partner_hospitals (
    partner_id  TEXT        PRIMARY KEY,
    name        TEXT        NOT NULL,
    address     TEXT        NOT NULL,
    phone       TEXT        NOT NULL,
    specialties TEXT[]      NOT NULL DEFAULT '{}'
);

-- --- 新建表：referrals（转诊记录，租户私有） ----------------------------------
CREATE TABLE IF NOT EXISTS referrals (
    referral_id TEXT        PRIMARY KEY,
    tenant_id   TEXT        NOT NULL,
    customer_id TEXT        NOT NULL,
    pet_id      TEXT        NOT NULL,
    partner_id  TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_referrals_tenant_id ON referrals (tenant_id);

ALTER TABLE referrals ENABLE ROW LEVEL SECURITY;
ALTER TABLE referrals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON referrals;
CREATE POLICY tenant_isolation ON referrals
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));
