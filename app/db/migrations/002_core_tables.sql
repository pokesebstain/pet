-- 迁移 002：创建核心业务表（对应设计文档 Data Models 4.1 / 4.2 / 4.3）。
-- 所有携带 tenant_id 的表均为多租户表，其行级安全策略在迁移 004 中定义。
-- knowledge_chunks.embedding 使用 pgvector 的 vector 类型（默认 1024 维）。
-- health_metrics 在迁移 003 中转换为 TimescaleDB 超表，主键包含时间列 ts。
-- 采用 IF NOT EXISTS 保证幂等，便于在开发/测试环境反复执行。

-- 4.1 多租户与核心实体 ------------------------------------------------------

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   TEXT        PRIMARY KEY,
    store_name  TEXT        NOT NULL,
    plan_tier   TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT        PRIMARY KEY,
    tenant_id     TEXT        NOT NULL,
    name          TEXT        NOT NULL,
    phone         TEXT        NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL,
    ltv           DOUBLE PRECISION,
    churn_score   DOUBLE PRECISION,
    segment       TEXT
);
CREATE INDEX IF NOT EXISTS ix_customers_tenant_id ON customers (tenant_id);

CREATE TABLE IF NOT EXISTS pets (
    pet_id     TEXT        PRIMARY KEY,
    tenant_id  TEXT        NOT NULL,
    owner_id   TEXT        NOT NULL,
    species    TEXT        NOT NULL,
    breed      TEXT        NOT NULL,
    birth_date TIMESTAMPTZ NOT NULL,
    weight_kg  DOUBLE PRECISION NOT NULL,
    life_stage TEXT
);
CREATE INDEX IF NOT EXISTS ix_pets_tenant_id ON pets (tenant_id);
CREATE INDEX IF NOT EXISTS ix_pets_owner_id ON pets (owner_id);

-- 4.2 时序 / 事件 / 向量 ----------------------------------------------------

-- 健康时序表：主键包含分区列 ts（TimescaleDB 超表要求唯一约束包含分区列）。
CREATE TABLE IF NOT EXISTS health_metrics (
    pet_id           TEXT             NOT NULL,
    tenant_id        TEXT             NOT NULL,
    ts               TIMESTAMPTZ      NOT NULL,
    weight_kg        DOUBLE PRECISION NOT NULL,
    activity_minutes DOUBLE PRECISION NOT NULL,
    food_intake_g    DOUBLE PRECISION NOT NULL,
    CONSTRAINT pk_health_metrics PRIMARY KEY (pet_id, ts)
);
CREATE INDEX IF NOT EXISTS ix_health_metrics_tenant_id ON health_metrics (tenant_id);

CREATE TABLE IF NOT EXISTS domain_events (
    event_id    TEXT        PRIMARY KEY,
    tenant_id   TEXT        NOT NULL,
    event_type  TEXT        NOT NULL,
    payload     JSONB       NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_domain_events_tenant_id ON domain_events (tenant_id);
CREATE INDEX IF NOT EXISTS ix_domain_events_event_type ON domain_events (event_type);

-- pgvector 知识片段：tenant_id 可为空表示平台级共享知识（对所有租户可见）。
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id    TEXT         PRIMARY KEY,
    tenant_id   TEXT,
    content     TEXT         NOT NULL,
    embedding   vector(1024) NOT NULL,
    source_type TEXT         NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_tenant_id ON knowledge_chunks (tenant_id);

CREATE TABLE IF NOT EXISTS feature_vectors (
    entity_id     TEXT        NOT NULL,
    tenant_id     TEXT        NOT NULL,
    feature_group TEXT        NOT NULL,
    features      JSONB       NOT NULL,
    computed_at   TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_feature_vectors PRIMARY KEY (entity_id, feature_group)
);
CREATE INDEX IF NOT EXISTS ix_feature_vectors_tenant_id ON feature_vectors (tenant_id);

-- 4.3 订阅与供应链 ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id TEXT        PRIMARY KEY,
    tenant_id       TEXT        NOT NULL,
    customer_id     TEXT        NOT NULL,
    plan_id         TEXT        NOT NULL,
    status          TEXT        NOT NULL,
    next_billing_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_subscriptions_tenant_id ON subscriptions (tenant_id);
CREATE INDEX IF NOT EXISTS ix_subscriptions_customer_id ON subscriptions (customer_id);

CREATE TABLE IF NOT EXISTS skus (
    sku_id         TEXT             PRIMARY KEY,
    tenant_id      TEXT             NOT NULL,
    name           TEXT             NOT NULL,
    category       TEXT             NOT NULL,
    unit_cost      NUMERIC(18, 2)   NOT NULL,
    current_stock  DOUBLE PRECISION NOT NULL,
    lead_time_days DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_skus_tenant_id ON skus (tenant_id);
