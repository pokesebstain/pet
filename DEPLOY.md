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

## 链路监控（Prometheus + LangFuse）

2C2G 机器内存有限，**不在本机自建 Prometheus/Grafana/LangFuse**（自建 LangFuse 需要额外
的 ClickHouse，内存开销远超余量），改用云端方案：

### Prometheus 指标（运行时耗时 / 错误率）

- 应用已暴露 `GET /metrics`（Prometheus 文本格式），涵盖：HTTP 请求耗时与状态码、
  云端 LLM 调用结果（success/timeout/rate_limited/unavailable/degraded）、Supervisor
  意图识别分布、接待预约门控判定分布、企业微信回调结果。
- **不对公网开放**：`docker/nginx.conf` 已拦截 `/metrics` 返回 403。
- 抓取方式：让 Prometheus / Grafana Cloud Agent 在同一 Docker 网络内直连
  `http://app:8000/metrics`（不经过 nginx），或用 Grafana Cloud 的远程写入 Agent
  （免费层足够单店用量，不占本机额外内存）。

### LangFuse（Agent 决策链全链路追溯）

- 到 [LangFuse Cloud](https://cloud.langfuse.com) 注册项目，在 Settings → API Keys
  获取 Public Key / Secret Key，填入 `.env`：
  ```
  PETOPS_LANGFUSE_PUBLIC_KEY=pk-lf-xxxx
  PETOPS_LANGFUSE_SECRET_KEY=sk-lf-xxxx
  ```
- 留空则回退进程内追溯（仅用于本地调试，不出站，重启即丢失）。
- 每轮对话会上报一条 trace（含意图识别 / 路由 / 各专家 / 反思 / 聚合 / HITL 各节点的
  输入输出与耗时），可在 LangFuse 控制台按 `session_id`（对应 `thread_id`）查看同一
  客户的多轮对话全链路，排查"为什么没识别到预约意图""为什么走了 HITL"等问题。
- 上报失败（网络问题等）不影响主业务流程，仅记录 WARNING 日志。
