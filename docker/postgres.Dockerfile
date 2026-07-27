# PostgreSQL 16 + pgvector + TimescaleDB（单节点，供单门店部署）。
# 基于官方 postgres 镜像（已内置 PGDG apt 源），额外安装 pgvector 与 TimescaleDB。
FROM postgres:16-bookworm

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates gnupg wget lsb-release \
        postgresql-16-pgvector; \
    # 添加 TimescaleDB apt 源
    echo "deb https://packagecloud.io/timescale/timescaledb/debian/ $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/timescaledb.list; \
    wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg; \
    apt-get update; \
    apt-get install -y --no-install-recommends timescaledb-2-postgresql-16; \
    rm -rf /var/lib/apt/lists/*

# btree_gist（预约防超卖排他约束所需）随 postgresql-contrib 已内置于基础镜像。
# shared_preload_libraries=timescaledb 在 compose 的 command 中设置。
