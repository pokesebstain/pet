-- 迁移 003：将 health_metrics 转换为 TimescaleDB 超表（hypertable）。
-- 按时间列 ts 自动分区，支撑最近 30 天时序异常检测等查询（Requirements 9.1）。
-- if_not_exists / migrate_data 保证已存在数据与重复执行的安全性（幂等）。

SELECT create_hypertable(
    'health_metrics',
    'ts',
    if_not_exists      => TRUE,
    migrate_data       => TRUE,
    chunk_time_interval => INTERVAL '7 days'
);
