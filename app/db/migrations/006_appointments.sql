-- 迁移 006：企业微信预约排期表、RLS 策略与防超卖并发约束（对应设计 14.4 / 14.7.3；任务 26.2）。
--
-- 覆盖表：grooming_resources（洗护资源）、business_hours（营业时间）、
--         slot_capacities（时段容量行）、appointments（预约记录）。
-- 全部为多租户表：tenant_id 非空，启用并强制 RLS，策略基于会话变量 app.current_tenant
-- （与迁移 004 一致：未设置租户上下文时 current_setting(..., TRUE) 返回 NULL → 零可见行）。
--
-- 防超卖双保险（Requirements 22.2、24.1）：
--   1) slot_capacities 为每个 (tenant_id, service_type, start_at) 维护一行容量记录，
--      供 book_appointment 事务内 `SELECT … FOR UPDATE` 加锁，串行化同槽并发预约（14.7.3）。
--   2) appointments 上的排他约束（EXCLUDE USING gist）阻止同一 resource_id 处于
--      PENDING/CONFIRMED 状态的预约在时间上重叠（tstzrange && 重叠 + resource_id/tenant_id 相等）。
--
-- 排他约束需 btree_gist 扩展以支持在 GiST 索引中对 text 列做等值（WITH =）比较。
-- 采用 IF NOT EXISTS / DROP POLICY IF EXISTS 保证迁移幂等；排他约束内联于 CREATE TABLE，
-- 从而随建表一并幂等创建（表已存在时整段跳过）。

-- 支撑排他约束中 tenant_id / resource_id 的等值比较（GiST）。
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- --- 建表 -------------------------------------------------------------------

-- 洗护资源（工位/店员）：容量 = 同一时段可并行服务的资源数。
CREATE TABLE IF NOT EXISTS grooming_resources (
    resource_id  TEXT    PRIMARY KEY,
    tenant_id    TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    service_type TEXT    NOT NULL,
    active       BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_grooming_resources_tenant_id
    ON grooming_resources (tenant_id);

-- 门店营业时间（按星期，0=周一 … 6=周日；应用层校验 open_time < close_time）。
CREATE TABLE IF NOT EXISTS business_hours (
    tenant_id  TEXT    NOT NULL,
    weekday    INTEGER NOT NULL,
    open_time  TIME    NOT NULL,
    close_time TIME    NOT NULL,
    CONSTRAINT pk_business_hours PRIMARY KEY (tenant_id, weekday)
);
CREATE INDEX IF NOT EXISTS ix_business_hours_tenant_id
    ON business_hours (tenant_id);

-- 时段容量行：book_appointment 事务内 `SELECT … FOR UPDATE` 的加锁对象，
-- 串行化对同一 (tenant_id, service_type, start_at) 的并发预约，杜绝超卖。
CREATE TABLE IF NOT EXISTS slot_capacities (
    tenant_id    TEXT        NOT NULL,
    service_type TEXT        NOT NULL,
    start_at     TIMESTAMPTZ NOT NULL,
    end_at       TIMESTAMPTZ NOT NULL,
    capacity     INTEGER     NOT NULL,
    CONSTRAINT pk_slot_capacities PRIMARY KEY (tenant_id, service_type, start_at)
);
CREATE INDEX IF NOT EXISTS ix_slot_capacities_tenant_id
    ON slot_capacities (tenant_id);

-- 预约记录：排他约束确保同一资源的有效预约时间不重叠（防双重占位）。
-- resource_id 为空（尚未分配资源）或状态非 PENDING/CONFIRMED（已取消/完成）的行不参与约束。
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id TEXT        PRIMARY KEY,
    tenant_id      TEXT        NOT NULL,
    customer_id    TEXT        NOT NULL,
    pet_id         TEXT        NOT NULL,
    service_type   TEXT        NOT NULL,
    start_at       TIMESTAMPTZ NOT NULL,
    end_at         TIMESTAMPTZ NOT NULL,
    resource_id    TEXT,
    status         TEXT        NOT NULL,
    source         TEXT        NOT NULL DEFAULT 'wecom',
    created_at     TIMESTAMPTZ NOT NULL,
    CONSTRAINT excl_appointments_resource_overlap
        EXCLUDE USING gist (
            tenant_id WITH =,
            resource_id WITH =,
            tstzrange(start_at, end_at) WITH &&
        )
        WHERE (status IN ('pending', 'confirmed') AND resource_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_appointments_tenant_id ON appointments (tenant_id);
CREATE INDEX IF NOT EXISTS ix_appointments_customer_id ON appointments (customer_id);
CREATE INDEX IF NOT EXISTS ix_appointments_pet_id ON appointments (pet_id);

-- --- 行级安全（RLS）：租户隔离，策略基于会话变量 app.current_tenant ---------

-- grooming_resources
ALTER TABLE grooming_resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE grooming_resources FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON grooming_resources;
CREATE POLICY tenant_isolation ON grooming_resources
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- business_hours
ALTER TABLE business_hours ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_hours FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON business_hours;
CREATE POLICY tenant_isolation ON business_hours
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- slot_capacities
ALTER TABLE slot_capacities ENABLE ROW LEVEL SECURITY;
ALTER TABLE slot_capacities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON slot_capacities;
CREATE POLICY tenant_isolation ON slot_capacities
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));

-- appointments
ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON appointments;
CREATE POLICY tenant_isolation ON appointments
    USING (tenant_id = current_setting('app.current_tenant', TRUE))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));
