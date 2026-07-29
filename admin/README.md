# PetOps Admin Dashboard

Vue 3 单页后台，覆盖 6 大 agent 意图分支的数据可视化与 CRUD。

## 入口

`https://<你的域名>/admin/`

后端 API 前缀：`/api/admin/*`（nginx 反代到 FastAPI）。

## 技术栈

- **前端**：Vue 3.5 + Vite 5 + TypeScript 5 + Element Plus 2.8 + Pinia 2 + vue-router 4 + axios
- **后端**：FastAPI 0.118 + SQLAlchemy 2.0 + Pydantic v2（已有后端代码新增 `app/api/admin_routes.py`）
- **测试**：Vitest 2 + @vue/test-utils

## 本地开发

```bash
# 前端开发服务器
cd admin
npm install
npm run dev
# → http://localhost:5173/admin/
# Vite 已配 proxy：/api → http://localhost:8000

# 后端
cd ../
docker compose up -d db app
# FastAPI 自动迁移 + 跑在 :8000
```

## 生产部署

```bash
# 1. 拉最新代码
git pull --ff-only

# 2. 重建 admin 镜像（含前端构建）
docker compose build admin
docker compose up -d admin

# 3. 浏览器验证
# https://你的域名/admin/  → 仪表盘
```

admin 容器内置 nginx，监听 80；主 nginx 通过 `location /admin/` 反代到 `http://admin:80/`。

## 目录结构

```
admin/
├── src/
│   ├── main.ts                  # Vue 应用入口
│   ├── App.vue
│   ├── router/index.ts          # 完整路由表（17 条）
│   ├── api/                     # axios + 资源 API 客户端
│   ├── stores/                  # Pinia
│   ├── components/
│   │   ├── common/              # DataTable / FormDrawer / StatCard
│   │   └── layout/              # Sidebar / Header / AppLayout
│   ├── views/                   # 14 个 .vue 视图
│   └── utils/                   # format / http
├── tests/                       # Vitest
├── vite.config.ts
└── package.json
```

## 13 个资源页面

| 路由 | 页面 | CRUD | 备注 |
|------|------|------|------|
| `/dashboard` | 仪表盘聚合 | 只读 | 5 个 stat 卡片 |
| `/customers` | 客户 | 全 CRUD | 软删 `deleted_at` |
| `/pets` | 宠物 | 全 CRUD | 硬删（关联少） |
| `/appointments` | 预约 | 全CRUD | 取消改 `status=cancelled`，不真删 |
| `/business-hours` | 营业时间 | **仅 list+edit** | 配置类 |
| `/resources` | 美容资源 | **仅 list+edit** | 配置类 |
| `/health/metrics` | 健康指标 | 只读 | 按 pet_id 过滤 |
| `/health/alerts` | 健康告警 | 确认告警 | POST `/alerts/{id}/ack` |
| `/operations/ltv` | LTV 分群 | 只读 | 聚合卡片 |
| `/operations/churn` | 流失风险 | 只读 | 阈值可调 |
| `/supply/skus` | SKU | list（PUT 占位） | 低库存标红 |
| `/marketing/contents` | 营销内容 | 手动触发生成 | POST `/contents/generate` |
| `/subscriptions` | 订阅 | 只读 | 含计费报告子路由 |
| `/ecosystem/partners` | 合作医院+转诊 | 只读 | 两个表格 |
| `/traces` | Agent 对话追溯 | 只读 | 列表+详情 |

## 测试

```bash
cd admin
npm run test          # 跑一次
npm run test:watch    # 持续
```

当前覆盖：
- `DataTable.vue` — 渲染、分页事件
- `StatCard.vue` — 渲染、上升/下降趋势
- `http.ts` — listPage / getOne / createOne / updateOne / deleteOne

**13/13 pass**

后端测试：
```bash
docker compose exec app python -m pytest tests/test_admin_routes.py -v
```

## 后端 API 一览

所有端点依赖 `X-Tenant-Id` header（单租户：从 `.env` 的 `PETOPS_DEFAULT_TENANT_ID`）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/health` | 探针 |
| GET/POST | `/api/admin/customers` | 客户列表 / 新建 |
| GET/PUT/DELETE | `/api/admin/customers/{id}` | 详情 / 更新 / 软删 |
| GET/POST | `/api/admin/pets` | 宠物 |
| GET/PUT/DELETE | `/api/admin/pets/{id}` | |
| GET/POST | `/api/admin/appointments` | 预约（含 status / customer_id 过滤）|
| GET/PUT/DELETE | `/api/admin/appointments/{id}` | DELETE = 改 status=cancelled |
| GET/PUT | `/api/admin/business-hours` | 配置类 |
| GET/PUT | `/api/admin/resources/{id}` | 配置类 |
| GET | `/api/admin/health/metrics` | 健康指标 |
| GET/POST | `/api/admin/health/alerts/{id}/ack` | 告警列表 / 确认 |
| GET | `/api/admin/operations/ltv` | LTV 分群 |
| GET | `/api/admin/operations/churn` | 流失风险 |
| GET | `/api/admin/operations/feature-vectors/{customer_id}` | 客户特征 |
| GET/PUT | `/api/admin/supply/skus/{id}` | SKU 列表 / 更新 |
| GET | `/api/admin/supply/restock-decisions` | 补货决策 |
| GET/POST | `/api/admin/marketing/contents` | 内容列表 |
| POST | `/api/admin/marketing/contents/generate` | 手动触发生成 |
| GET | `/api/admin/subscriptions` | 订阅列表 |
| GET | `/api/admin/subscriptions/{id}` | 详情 |
| GET | `/api/admin/subscriptions/billing-reports` | 计费报告（按月过滤）|
| GET | `/api/admin/ecosystem/partners` | 合作医院 |
| GET | `/api/admin/ecosystem/referrals` | 转诊 |
| GET | `/api/admin/traces` | 追溯列表 |
| GET | `/api/admin/traces/{thread_id}` | 追溯详情 |
| GET | `/api/admin/stats/overview` | 仪表盘聚合 |

## 不做（YAGNI / 按 plan 明确）

- 鉴权 / 登录（单兵开发，无外部用户）
- 审计日志
- E2E 测试
- 多租户切换（只服务当前单门店）
- 实时推送（WebSocket / SSE）
- RBAC 权限分级

## 故障排查

**`/admin/` 打开 404 / 白屏**
- `docker compose ps admin` 看容器是否 Up
- `docker compose logs --tail=50 admin` 看构建/启动错误
- `curl http://admin:80/` （容器内）看是否能返回 HTML

**后端 API 401**
- 确认请求带 `X-Tenant-Id` header
- nginx 反代路径 `/api/admin/ → app:8000/api/admin/` 是否正确

**前端构建失败**
- `cd admin && npm install` 重装
- 看 `vue-tsc` 报错的文件路径

**Vue 测试失败**
- `cd admin && npm run test` 看 vitest 输出
- 90% 是 mock 没设对（参考 `tests/http.spec.ts`）
