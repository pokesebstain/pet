-- 迁移 004：启用行级安全（RLS）并创建基于会话变量的租户隔离策略。
--
-- 策略核心：会话变量 app.current_tenant 由 RLS 上下文管理器（任务 2.2）通过
--   SET LOCAL app.current_tenant = '<tenant_id>'
-- 注入。使用 current_setting('app.current_tenant', TRUE) 的第二参数 TRUE，使变量
-- 未设置时返回 NULL 而非报错；此时任何 tenant_id 比较均为 NULL（不匹配），从而拒绝
-- 返回任何行——即"缺失租户上下文 → 零可见行"，满足 Requirements 5.1、5.2、5.4。
--
-- FORCE ROW LEVEL SECURITY 使表属主也受策略约束，避免应用以属主身份连接时绕过 RLS。
-- 使用 DROP POLICY IF EXISTS + CREATE POLICY 保证迁移幂等。

-- --- 标准租户表：tenant_id 必须等于当前会话租户 -----------------------------
-- tenants
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tenants;
CREATE POLICY tenant_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- customers
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON customers;
CREATE POLICY tenant_isolation ON customers
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- pets
ALTER TABLE pets ENABLE ROW LEVEL SECURITY;
ALTER TABLE pets FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON pets;
CREATE POLICY tenant_isolation ON pets
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- health_metrics
ALTER TABLE health_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE health_metrics FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON health_metrics;
CREATE POLICY tenant_isolation ON health_metrics
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- domain_events
ALTER TABLE domain_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE domain_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON domain_events;
CREATE POLICY tenant_isolation ON domain_events
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- feature_vectors
ALTER TABLE feature_vectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE feature_vectors FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON feature_vectors;
CREATE POLICY tenant_isolation ON feature_vectors
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- subscriptions
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON subscriptions;
CREATE POLICY tenant_isolation ON subscriptions
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- skus
ALTER TABLE skus ENABLE ROW LEVEL SECURITY;
ALTER TABLE skus FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON skus;
CREATE POLICY tenant_isolation ON skus
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- --- 共享可见表：租户私有 + 平台级共享（tenant_id 为空） ---------------------
-- knowledge_chunks：读取可见范围为"当前租户私有 + 平台级共享（tenant_id IS NULL）"，
-- 满足 RAG 检索租户可见性（Requirements 16.1、16.3）。写入仅允许归属当前租户或平台级
-- 共享（tenant_id IS NULL），由 WITH CHECK 约束。
ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_chunks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_visibility ON knowledge_chunks;
CREATE POLICY tenant_visibility ON knowledge_chunks
    USING (
        tenant_id = current_setting('app.current_tenant', TRUE)
        OR tenant_id IS NULL
    )
    WITH CHECK (
        tenant_id = current_setting('app.current_tenant', TRUE)
        OR tenant_id IS NULL
    );
