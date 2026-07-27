-- 迁移 001：启用必需的 PostgreSQL 扩展。
-- - vector       : pgvector，提供向量列与相似度检索（knowledge_chunks.embedding）。
-- - timescaledb  : TimescaleDB，提供时序超表（health_metrics）。
-- 使用 IF NOT EXISTS 保证迁移可重复执行（幂等）。

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS timescaledb;
