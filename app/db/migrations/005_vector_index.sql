-- 迁移 005：为 pgvector 向量列创建近邻检索索引。
-- 使用 IVFFlat + 余弦距离，加速 knowledge_chunks 的相似度检索（Requirements 16.1）。
-- lists 参数为分桶数，可依数据规模调优；小数据集下顺序扫描亦可正确工作，索引不影响结果正确性。

CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding
    ON knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
