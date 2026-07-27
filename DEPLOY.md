# PetOps 单门店部署（阿里云 2C2G）

面向单门店的最小生产部署。**不需要 GPU**：大模型走云端 API、视觉走第三方 API、无模型微调。

## 组件

| 服务 | 说明 | 内存上限 |
|------|------|----------|
| app | FastAPI + LangGraph 决策中枢（单进程 uvicorn） | 900 MB |
| db | PostgreSQL 16 + pgvector + TimescaleDB | 640 MB |
| redis | 事件总线 + 缓存 | 192 MB |
| nginx | HTTPS 反代（企业微信回调需 80/443） | 64 MB |

对象存储用**阿里云 OSS**（外部），不自建 MinIO，省内存与磁盘。

## 一次性准备

1. 安装 Docker 与 Docker Compose 插件。
2. **加 2 GiB Swap**（2 GiB 内存兜底，强烈建议）：
   ```bash
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
   sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```
3. 配置环境变量：
   ```bash
   cp .env.template .env   # 然后填写数据库密码、云端 LLM Key、企业微信参数等
   ```
4. HTTPS 证书（企业微信回调要求公网 + 443）：把证书放到 `docker/certs/fullchain.pem` 与
   `docker/certs/privkey.pem`（阿里云免费 SSL 证书或 certbot 签发），并把 `docker/nginx.conf`
   里的 `server_name` 改成你的域名。

## 启动

```bash
docker compose up -d --build
docker compose logs -f app      # 观察迁移执行与启动
curl http://localhost/health    # 经 nginx 到 app，应返回 {"status":"ok"}
```

首次启动时 app 容器会自动：等待数据库就绪 → 执行数据库迁移（幂等）→ 启动服务。

## 企业微信回调配置

- 管理后台「接收消息服务器配置 → URL」填：`https://<你的域名>/wecom/callback`
- Token / EncodingAESKey 必须与 `.env` 中 `PETOPS_WECOM_TOKEN` / `PETOPS_WECOM_ENCODING_AES_KEY` 一致
- 保存时企业微信会发 GET 验证；本服务已实现验签 + echostr 解密握手

## 2C2G 资源说明

- 各服务已设 `mem_limit`，合计约 1.8 GB，余量给操作系统 + Swap。
- Postgres 已调优（shared_buffers=256MB、max_connections=30 等）。
- 单店低并发场景够用。**上量或多店** → 升级 2C4G，或把 db/redis 迁到阿里云 RDS + 云 Redis。

## 运维观察

```bash
free -m                         # 看内存水位（关注 available 与 swap 使用）
docker stats                    # 看各容器实际内存/CPU
docker compose exec db psql -U petops -c "SELECT count(*) FROM pg_stat_activity;"
```

内存长期逼近上限或频繁用满 Swap，就该升配了。
