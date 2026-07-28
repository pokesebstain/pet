# PetOps Admin Dashboard 设计

> 日期：2026-07-28
> 类型：功能扩展（完整后台管理系统）
> 状态：已批准 / 待实施

## 目标

为 PetOps 提供一个 Vue 3 单页后台，覆盖 6 大 agent 意图分支所需的所有数据，让店主能在浏览器中**查看与修改**门店的运营数据。

## 范围（在脑暴中确认）

- **数据范围**：全量 6 大分支（reception / analysis / operation / health / supply / marketing）
- **读写**：可读 + 可改全部
- **租户**：只服务当前单门店（基于 `.env` 默认租户）
- **技术栈**：Vue 3 + Vite + Element Plus + vue-router + pinia
- **部署**：nginx 子路径 `/admin/`，Vue 独立容器提供静态资源

## 架构

```
[ 浏览器 ]
   ↓ HTTPS
[ nginx (主) ]
   ├── /admin/           → 反代 → admin 容器 (内置 nginx :80)
   ├── /api/admin/*      → 反代 → FastAPI :8000  ← 新增 admin_routes.py
   └── /wecom/callback   → 反代 → FastAPI :8000  (既有)
```

新增：
- `app/api/admin_routes.py` — 后端管理类端点（按资源分 router）
- `admin/` — Vue 3 项目（前端）
- `docker/admin.Dockerfile` — Vue 多阶段构建（node:20-alpine → nginx:alpine）
- 修改 `docker/nginx.conf`、`docker-compose.yml`

## 后端 API 设计

所有端点挂在 `/api/admin/` 前缀下，统一依赖 `require_tenant`（复用既有 RLS 上下文）。

### 资源端点（13 个资源，全 CRUD）

| 资源 | 端点 |
|------|------|
| 客户 | `GET/POST /customers`、`GET/PUT/DELETE /customers/{id}` |
| 宠物 | `GET/POST /pets`、`GET/PUT/DELETE /pets/{id}` |
| 预约 | `GET/POST /appointments`、`GET/PUT/DELETE /appointments/{id}` |
| 营业时间 | `GET /business-hours`、`PUT /business-hours/{weekday}` |
| 美容资源 | `GET/POST /resources`、`PUT/DELETE /resources/{id}` |
| 健康指标 | `GET /health/metrics`（按 pet_id / 时间范围） |
| 健康告警 | `GET /health/alerts`、`POST /health/alerts/{id}/ack` |
| LTV 分群 | `GET /operations/ltv` |
| 流失风险 | `GET /operations/churn` |
| 客户特征 | `GET /operations/feature-vectors/{customer_id}` |
| SKU | `GET /supply/skus`、`PUT /supply/skus/{id}` |
| 补货决策 | `GET /supply/restock-decisions` |
| 营销内容 | `GET /marketing/contents`、`POST /marketing/contents/generate` |
| 订阅 | `GET /subscriptions`、`GET /subscriptions/{id}`、`GET /subscriptions/billing-reports` |
| 合作医院 | `GET /ecosystem/partners` |
| 转诊 | `GET /ecosystem/referrals` |
| 对话历史 | `GET /traces`、`GET /traces/{thread_id}` |
| 仪表盘聚合 | `GET /stats/overview` |

### 统一约定

- **分页**：`?page=1&page_size=20`，返回 `{items, total, page, page_size}`
- **错误**：FastAPI `HTTPException` 标准；数据约束违反 → 409 Conflict
- **软删**：customers / pets 加 `deleted_at`；appointments 取消改 `status=cancelled`，不真删
- **不新增外部依赖**：复用既有 SQLAlchemy session / models / engines

## 前端设计

```
admin/
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── router/index.ts
│   ├── stores/                       # Pinia 状态
│   ├── api/
│   │   ├── client.ts                # axios 实例（baseURL=/api/admin）
│   │   ├── customers.ts
│   │   ├── pets.ts
│   │   ├── ...
│   ├── views/                       # 13 个资源 + Dashboard
│   ├── components/
│   │   ├── layout/                  # Sidebar / Header / AppLayout
│   │   └── common/                  # DataTable / FormDrawer / StatCard
│   └── utils/
├── vite.config.ts                   # base='/admin/'
├── package.json
├── tsconfig.json
└── Dockerfile
```

### 关键决策

1. **路由**：嵌套路由 + 侧边栏分组
   ```
   /admin/                  → Dashboard
   /admin/customers         → 客户列表
   /admin/customers/:id     → 客户详情
   /admin/pets              → ...
   /admin/appointments      → ...
   /admin/health/metrics    → ...
   /admin/operations/ltv    → ...
   ```

2. **通用组件**：
   - **DataTable**：分页 + 搜索 + 排序 + 操作列（基于 Element Plus `el-table` + `el-pagination`），每页 20 条
   - **FormDrawer**：右侧抽屉式表单（基于 `el-drawer`），创建 / 编辑复用
   - **StatCard**：仪表盘数字卡片（带趋势箭头）

3. **状态**：Pinia store 按资源分；列表筛选条件放 store，刷新后保留（localStorage 同步）

4. **错误处理**：axios 拦截器统一处理 4xx/5xx → `ElMessage` 提示

5. **TypeScript**：vue-tsc + vite-plugin-vue，类型与后端 Pydantic 对齐

6. **样式**：Element Plus 默认主题；SCSS 写自定义 token

## 部署

### `docker/admin.Dockerfile`（多阶段）

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY admin/package*.json ./
RUN npm ci
COPY admin/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
```

### `docker-compose.yml` 增量

```yaml
services:
  admin:
    build:
      context: .
      dockerfile: docker/admin.Dockerfile
    restart: unless-stopped
    volumes:
      - ./docker/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    mem_limit: 64m
    cpus: 0.25
```

### `docker/nginx.conf` 增量

```nginx
location /admin/ {
    proxy_pass http://admin:80/;
}
```

### 本地开发

```bash
cd admin
npm install
npm run dev  # localhost:5173，proxy /api → localhost:8000
```

## 测试

**后端**：`tests/test_admin_routes.py`
- FastAPI `TestClient` + 内存伪 db
- 每个端点 list / get / create / update / delete 主路径
- ~80 测试用例

**前端**：`admin/tests/`
- Vitest + Vue Test Utils
- 重点测通用组件（DataTable 分页 / FormDrawer 校验 / StatCard）
- ~20 用例

**不做 E2E**（单兵作战、E2E 性价比低）

**验收清单**：
- 后端 80+ 测试通过
- 前端 20+ 测试通过
- `docker compose up -d` 一键起所有服务（含 admin）
- 浏览器打开 `https://域名/admin/` 看到 dashboard
- 每个资源能完成"列表 → 新建 → 编辑 → 删除"全流程
- 现有 538+ 测试仍通过，未破坏既有功能

## 排期

| 阶段 | 内容 | 天数 |
|------|------|------|
| D1 | 项目脚手架：Vue 初始化 + Vite/Docker/nginx 集成 + Hello World | 0.5 |
| D2 | 后端骨架：admin_routes 框架 + 统一响应/错误 + 测试基础 | 1 |
| D3-D4 | 后端 13 资源 CRUD 端点 + 对应测试 | 3 |
| D5 | 后端：仪表盘聚合 / traces 接口 + 联调 | 0.5 |
| D6-D7 | 前端：通用组件（DataTable/FormDrawer/StatCard/Layout）+ 路由 + axios | 1.5 |
| D8 | 前端 13 资源页面（按资源分批） | 2 |
| D9 | 前端测试 + 整体联调 + 修 bug + 文档 | 1 |

**总计：6-9 天**

## 风险

1. **RLS 上下文**：写操作要确保租户 ID 注入 SQLAlchemy session；`Depends(require_tenant)` 应足够，但需测试覆盖
2. **两层 nginx**：admin 容器内置 nginx + 主 nginx 反代，可能踩到路径 / 跨域；开发期要测好
3. **数据量大时**：列表必须服务端分页 + 服务端搜索；前端不能全量加载

## 不做（YAGNI）

- 鉴权 / 登录（用户明确不要）
- 审计日志（用户明确不要）
- E2E 测试
- 多租户切换（用户选单租户）
- 实时推送（WebSocket / SSE）—— 用轮询够用
- 复杂权限分级（RBAC）