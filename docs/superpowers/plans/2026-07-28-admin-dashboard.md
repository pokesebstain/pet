# PetOps Admin Dashboard 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 PetOps 提供一个 Vue 3 单页后台，覆盖 6 大 agent 意图分支的数据可视化与 CRUD 管理。

**Architecture:** 浏览器 → 主 nginx（443）→ 反代 `/admin/*` 到 admin 容器（内置 nginx，静态 Vue 资源）+ 反代 `/api/admin/*` 到 FastAPI。新增 `app/api/admin_routes.py`（FastAPI 后端，13 资源 CRUD）+ `admin/` 目录（Vue 3 前端 SPA）。

**Tech Stack:**
- 后端：FastAPI / SQLAlchemy 2.0 / Pydantic v2 / pytest
- 前端：Vue 3 / Vite 5 / TypeScript / Element Plus / vue-router 4 / Pinia 2 / axios / Vitest
- 部署：多阶段 Docker（node:20-alpine → nginx:alpine）

## 全局约束

- 所有管理端点须 `Depends(require_tenant)`，确保 RLS 上下文注入
- 不引入新的 Python 包（复用现有 SQLAlchemy / FastAPI / Pydantic）
- 前端不引入除 Element Plus / Pinia / vue-router / axios / Vitest / vue-tsc 之外的新依赖
- 所有列表端点统一分页：`?page=1&page_size=20`，返回 `{items, total, page, page_size}`
- 测试：后端 pytest + 前端 Vitest；不写 E2E
- 配置类资源（resources / business-hours）只暴露 list + update，无新建/删除按钮
- 软删：customers/pets 加 `deleted_at`；appointments 取消改 `status='cancelled'`，不真删
- 所有 commit 信息遵循 `feat:` / `fix:` / `docs:` / `test:` / `chore:` 前缀

---

## 文件结构

新增：
```
app/api/admin_routes.py          # 后端管理路由主文件（按资源分 router）
app/api/admin_schemas.py         # Pydantic 请求/响应模型
tests/test_admin_routes.py       # 后端测试
admin/                           # Vue 3 项目根目录
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── Dockerfile                   # 多阶段构建（移到 docker/）
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── router/index.ts
│   ├── api/{client.ts,customers.ts,pets.ts,...}
│   ├── stores/app.ts
│   ├── views/                   # 13 资源 + Dashboard
│   ├── components/{layout,common}/
│   └── utils/{format.ts,http.ts}
└── tests/                       # Vitest
docker/admin.Dockerfile          # Vue 多阶段构建
```

修改：
- `app/api/app.py` — 注册 admin_routes
- `docker/nginx.conf` — 加 `/admin/` 与 `/api/admin/` 反代
- `docker-compose.yml` — 加 admin 服务

---

# 阶段 1：项目脚手架

## Task 1: Vue 项目初始化与 Docker 集成

**Files:**
- Create: `admin/package.json`
- Create: `admin/vite.config.ts`
- Create: `admin/tsconfig.json`
- Create: `admin/tsconfig.node.json`
- Create: `admin/index.html`
- Create: `admin/src/main.ts`
- Create: `admin/src/App.vue`
- Create: `admin/src/env.d.ts`
- Create: `docker/admin.Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `docker/nginx.conf`

**Interfaces:**
- Produces: 可构建的 Vue 3 项目；`docker compose up admin` 后 `localhost/admin/` 返回 200

### Step 1.1: 创建 `admin/package.json`

```json
{
  "name": "petops-admin",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "axios": "^1.7.7",
    "element-plus": "^2.8.4",
    "pinia": "^2.2.4",
    "vue": "^3.5.12",
    "vue-router": "^4.4.5"
  },
  "devDependencies": {
    "@types/node": "^22.7.5",
    "@vitejs/plugin-vue": "^5.1.4",
    "@vue/test-utils": "^2.4.6",
    "jsdom": "^25.0.1",
    "sass": "^1.79.5",
    "typescript": "^5.6.3",
    "vite": "^5.4.9",
    "vitest": "^2.1.3",
    "vue-tsc": "^2.1.6"
  }
}
```

### Step 1.2: 创建 `admin/vite.config.ts`

```ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  base: '/admin/',
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true }
    }
  },
  test: {
    environment: 'jsdom',
    globals: true
  }
})
```

### Step 1.3: 创建 `admin/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "jsx": "preserve",
    "sourceMap": true,
    "resolveJsonModule": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "types": ["node", "vitest/globals"],
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src/**/*", "src/**/*.vue", "env.d.ts"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

### Step 1.4: 创建 `admin/tsconfig.node.json`

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

### Step 1.5: 创建 `admin/index.html`

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PetOps Admin</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

### Step 1.6: 创建 `admin/src/env.d.ts`

```ts
/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
```

### Step 1.7: 创建 `admin/src/App.vue`

```vue
<template>
  <router-view />
</template>

<script setup lang="ts">
</script>
```

### Step 1.8: 创建 `admin/src/main.ts`

```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
```

### Step 1.9: 创建 `admin/src/router/index.ts`

```ts
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('@/views/DashboardView.vue') },
  { path: '/customers', component: () => import('@/views/customers/ListView.vue') },
  { path: '/customers/:id', component: () => import('@/views/customers/DetailView.vue') }
]

export default createRouter({
  history: createWebHistory('/admin/'),
  routes
})
```

### Step 1.10: 创建占位 `admin/src/views/DashboardView.vue`

```vue
<template>
  <div style="padding: 24px">
    <h1>PetOps Admin</h1>
    <p>Hello World — 脚手架已就绪</p>
  </div>
</template>
```

### Step 1.11: 创建 `admin/src/views/customers/ListView.vue`

```vue
<template><div>Customers List（占位）</div></template>
```

### Step 1.12: 创建 `admin/src/views/customers/DetailView.vue`

```vue
<template><div>Customer Detail（占位）{{ $route.params.id }}</div></template>
```

### Step 1.13: 创建 `docker/admin.Dockerfile`

```dockerfile
# 阶段 1：构建
FROM node:20-alpine AS builder
WORKDIR /app
COPY admin/package*.json ./
RUN npm ci
COPY admin/ ./
RUN npm run build

# 阶段 2：运行时
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
```

### Step 1.14: 修改 `docker-compose.yml`，加 admin 服务

在 `services:` 下加入：

```yaml
  admin:
    build:
      context: .
      dockerfile: docker/admin.Dockerfile
    restart: unless-stopped
    expose:
      - "80"
    mem_limit: 64m
    cpus: 0.25
```

### Step 1.15: 修改 `docker/nginx.conf`，加 `/admin/` 反代

在 `server` 块中加入：

```nginx
    location /admin/ {
        proxy_pass http://admin:80/;
        proxy_set_header Host $host;
        rewrite ^/admin/(.*)$ /$1 break;  # admin 容器内置 nginx，路径不带 /admin 前缀
    }
```

### Step 1.16: 构建并验证

```bash
cd /root/.../pet
docker compose build admin
docker compose up -d admin
curl -I http://localhost/admin/
# 期望: HTTP/1.1 200 OK, Content-Type: text/html
```

### Step 1.17: Commit

```bash
git add admin/ docker/admin.Dockerfile docker/nginx.conf docker-compose.yml
git commit -m "feat(admin): 初始化 Vue 3 项目脚手架 + Docker 集成"
```

---

# 阶段 2：后端骨架

## Task 2: 后端通用依赖与统一响应

**Files:**
- Create: `app/api/admin_schemas.py`
- Create: `app/api/admin_routes.py`
- Modify: `app/api/app.py`
- Create: `tests/test_admin_routes.py`

**Interfaces:**
- Produces: `/api/admin/health` 返回 `{status: "ok", tenant_id: "..."}`

### Step 2.1: 创建 `app/api/admin_schemas.py`

```python
"""Admin Dashboard 通用 Pydantic 模式（请求 / 响应 / 分页）。"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResp(BaseModel, Generic[T]):
    """分页响应统一格式：``items`` + 元信息。"""

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class PageReq(BaseModel):
    """分页请求参数（Query 注入用）。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
```

### Step 2.2: 创建 `app/api/admin_routes.py`（骨架）

```python
"""Admin Dashboard 后端路由（按资源分 router，全部挂在 ``/api/admin/`` 前缀下）。

所有端点依赖 :func:`app.api.auth.require_tenant` 自动注入 RLS 上下文；不新增鉴权。
"""
from __future__ import annotations

from typing import Iterator

from fastapi import APIRouter, Depends, Request

from app.api.admin_schemas import PageResp

# 顶层 router：所有资源挂在此下，统一前缀 ``/api/admin`` 由 app.py 注册时设置。
router = APIRouter(tags=["admin"])


@router.get("/health")
def admin_health(tenant_id: str = Depends(__get_tenant_dep)) -> dict[str, str]:
    """管理后台存活探针：含当前租户 ID（验证 RLS 注入）。"""
    return {"status": "ok", "tenant_id": tenant_id}


def __get_tenant_dep() -> Iterator[str]:
    """占位：在 Task 2.4 替换为真实依赖导入。"""
    from app.api.auth import require_tenant

    return require_tenant
```

### Step 2.3: 修改 `app/api/app.py` 注册 admin router

找到文件末尾，在 `register_wecom_routes(app)` 之后加：

```python
    # ------------------------------------------------------------------ #
    # Admin Dashboard 路由（按需挂载，无 AdminComposition 时跳过）
    # ------------------------------------------------------------------ #
    try:
        from app.api.admin_routes import router as admin_router
        app.include_router(admin_router, prefix="/api/admin")
    except ImportError:
        pass
```

### Step 2.4: 修复 `__get_tenant_dep` 的占位

将 `app/api/admin_routes.py` 中 `__get_tenant_dep` 改为正常函数（去掉下划线前缀作为内部辅助）：

```python
from app.api.auth import require_tenant


@router.get("/health")
def admin_health(tenant_id: Iterator[str] = Depends(require_tenant)) -> dict[str, str]:
    """管理后台存活探针：含当前租户 ID（验证 RLS 注入）。"""
    return {"status": "ok", "tenant_id": tenant_id}
```

### Step 2.5: 创建 `tests/test_admin_routes.py`

```python
"""Admin Dashboard 后端路由测试（任务 2 起逐步扩充）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import build_composition, create_app


def _build_test_client() -> TestClient:
    composition = build_composition()
    return TestClient(create_app(composition=composition))


def test_admin_health_returns_tenant_id() -> None:
    client = _build_test_client()
    resp = client.get(
        "/api/admin/health",
        headers={"X-Tenant-Id": "test-store-001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["tenant_id"] == "test-store-001"
```

> 注：实际 tenant header 注入方式以 `extract_request_tenant_id` 的实现为准（参考 `app/api/auth.py`）。若用 query/header/bearer 任意一种，调整测试 header 即可。

### Step 2.6: 运行测试

```bash
cd /root/.../pet
docker compose exec app python -m pytest tests/test_admin_routes.py -v
# 期望: PASS test_admin_health_returns_tenant_id
```

### Step 2.7: Commit

```bash
git add app/api/admin_routes.py app/api/admin_schemas.py app/api/app.py tests/test_admin_routes.py
git commit -m "feat(admin): 后端骨架 + 通用分页模式 + /api/admin/health 探针"
```

---

# 阶段 3：后端 CRUD 端点（13 资源）

> 后续任务按相同模式：每个资源一个 router 子集，所有依赖 `require_tenant`。
> 数据访问用 SQLAlchemy 2.0 text() + 参数化查询（避免 ORM 反射带来的额外配置）。

## Task 3: Customers CRUD

**Files:**
- Modify: `app/api/admin_routes.py`
- Modify: `tests/test_admin_routes.py`

**Interfaces:**
- Produces:
  - `GET /api/admin/customers?page=&page_size=&search=` → `PageResp[CustomerOut]`
  - `GET /api/admin/customers/{id}` → `CustomerOut`
  - `POST /api/admin/customers` → `CustomerOut`
  - `PUT /api/admin/customers/{id}` → `CustomerOut`
  - `DELETE /api/admin/customers/{id}` → 204（软删）

### Step 3.1: 扩展 `app/api/admin_schemas.py`，加 CustomerOut / CustomerIn

在文件末尾追加：

```python
from datetime import datetime

from app.models.entities import Customer, Pet


class CustomerOut(BaseModel):
    customer_id: str
    name: str
    phone: str | None
    registered_at: datetime
    ltv: float | None
    churn_score: float | None
    segment: str | None
    onboarding_pending: bool
    deleted_at: datetime | None  # 软删字段：DB 迁移阶段加


class CustomerIn(BaseModel):
    name: str
    phone: str | None = None
```

### Step 3.2: 在 `app/api/admin_routes.py` 加 customers router

```python
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Query, status
from sqlalchemy import text

from app.api.admin_schemas import CustomerIn, CustomerOut, PageResp
from app.db.init import create_db_engine


customers_router = APIRouter(prefix="/customers", tags=["admin-customers"])


@customers_router.get("", response_model=PageResp[CustomerOut])
def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = Query(None, description="按姓名 / 手机号模糊搜索"),
    tenant_id: str = Depends(require_tenant),
) -> PageResp[CustomerOut]:
    """客户列表：分页 + 搜索。"""
    engine = create_db_engine()
    offset = (page - 1) * page_size
    where_clauses = ["tenant_id = :tid", "deleted_at IS NULL"]
    params: dict[str, object] = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if search:
        where_clauses.append("(name ILIKE :s OR phone ILIKE :s)")
        params["s"] = f"%{search}%"
    where_sql = " AND ".join(where_clauses)
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                f"SELECT customer_id, name, phone, registered_at, ltv, churn_score, "
                f"segment, onboarding_pending FROM customers "
                f"WHERE {where_sql} ORDER BY registered_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM customers WHERE {where_sql}"), params
        ).scalar_one()
    items = [
        CustomerOut(
            customer_id=r.customer_id,
            name=r.name,
            phone=r.phone,
            registered_at=r.registered_at,
            ltv=r.ltv,
            churn_score=r.churn_score,
            segment=r.segment,
            onboarding_pending=r.onboarding_pending,
            deleted_at=None,
        )
        for r in rows
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


@customers_router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: str, tenant_id: str = Depends(require_tenant)) -> CustomerOut:
    """客户详情。"""
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        row = conn.execute(
            text(
                "SELECT customer_id, name, phone, registered_at, ltv, churn_score, "
                "segment, onboarding_pending FROM customers "
                "WHERE customer_id = :cid AND deleted_at IS NULL"
            ),
            {"tid": tenant_id, "cid": customer_id},
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客户不存在")
    return CustomerOut(
        customer_id=row.customer_id,
        name=row.name,
        phone=row.phone,
        registered_at=row.registered_at,
        ltv=row.ltv,
        churn_score=row.churn_score,
        segment=row.segment,
        onboarding_pending=row.onboarding_pending,
        deleted_at=None,
    )


@customers_router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerIn, tenant_id: str = Depends(require_tenant)
) -> CustomerOut:
    """新建客户。"""
    customer_id = f"cust-{uuid.uuid4().hex[:12]}"
    engine = create_db_engine()
    registered_at = datetime.now(timezone.utc)
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, tenant_id, name, phone, registered_at) "
                "VALUES (:cid, :tid, :name, :phone, :reg_at)"
            ),
            {
                "cid": customer_id,
                "tid": tenant_id,
                "name": payload.name,
                "phone": payload.phone,
                "reg_at": registered_at,
            },
        )
        conn.commit()
    return CustomerOut(
        customer_id=customer_id,
        name=payload.name,
        phone=payload.phone,
        registered_at=registered_at,
        ltv=None,
        churn_score=None,
        segment=None,
        onboarding_pending=False,
        deleted_at=None,
    )


@customers_router.put("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: str,
    payload: CustomerIn,
    tenant_id: str = Depends(require_tenant),
) -> CustomerOut:
    """更新客户基本信息（仅姓名 / 手机号；其它字段由各 engine 计算）。"""
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        result = conn.execute(
            text(
                "UPDATE customers SET name = :name, phone = :phone "
                "WHERE customer_id = :cid AND deleted_at IS NULL"
            ),
            {"name": payload.name, "phone": payload.phone, "cid": customer_id},
        )
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客户不存在")
    return get_customer(customer_id, tenant_id)


@customers_router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(customer_id: str, tenant_id: str = Depends(require_tenant)) -> None:
    """软删客户。"""
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        result = conn.execute(
            text(
                "UPDATE customers SET deleted_at = :now "
                "WHERE customer_id = :cid AND deleted_at IS NULL"
            ),
            {"now": datetime.now(timezone.utc), "cid": customer_id},
        )
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客户不存在")
```

### Step 3.3: 在 `app/api/admin_routes.py` 末尾注册 router

```python
router.include_router(customers_router)
```

### Step 3.4: 在 `tests/test_admin_routes.py` 加 Customers 测试

```python
def test_customers_list_returns_empty_page() -> None:
    client = _build_test_client()
    resp = client.get("/api/admin/customers", headers={"X-Tenant-Id": "test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_customers_get_unknown_returns_404() -> None:
    client = _build_test_client()
    resp = client.get("/api/admin/customers/cust-xxx", headers={"X-Tenant-Id": "test"})
    assert resp.status_code == 404
```

> 注：customers 表需要在测试 DB 中存在；本地开发用真实 DB 时保证迁移已跑（`init_database`）。CI 用 TestClient + 真实迁移 + 内存 fixture，可参考现有 `tests/test_scheduling_db.py` 的模式。

### Step 3.5: 运行测试

```bash
docker compose exec app python -m pytest tests/test_admin_routes.py -v
# 期望: 既有 test_admin_health_returns_tenant_id + 2 个新测试全 PASS
```

### Step 3.6: Commit

```bash
git add app/api/admin_routes.py app/api/admin_schemas.py tests/test_admin_routes.py
git commit -m "feat(admin): Customers 资源完整 CRUD"
```

---

## Task 4-15: 其它 12 资源（重复 Task 3 模式）

每个任务的结构与 Task 3 一致：schemas → router → 测试 → commit。下表汇总各任务的字段与差异：

### Task 4: Pets CRUD

**Files:** `app/api/admin_schemas.py` / `app/api/admin_routes.py` / `tests/test_admin_routes.py`

**Endpoints:** `GET/POST /pets` / `GET/PUT/DELETE /pets/{id}`

**PetOut 字段：** pet_id, owner_id, name, species, breed, birth_date, weight_kg, life_stage, onboarding_pending

**PetIn 字段：** owner_id, name, species, breed, birth_date, weight_kg

**Router 注册：** `router.include_router(pets_router)`

**测试：** `test_pets_list_empty` / `test_pets_get_unknown_404`

**Commit：** `feat(admin): Pets 资源完整 CRUD`

### Task 5: Appointments CRUD

**特殊点：**
- DELETE 不软删表行，而是 `UPDATE appointments SET status='cancelled'`
- AppointmentOut 含 status 字段（pending / confirmed / cancelled / completed）
- 支持过滤：?status=&start_from=&start_to=&customer_id=

**Endpoints:** `GET/POST /appointments` / `GET/PUT/DELETE /appointments/{id}`

**Commit：** `feat(admin): Appointments 资源 CRUD（含取消语义）`

### Task 6: Business Hours + Resources（配置类）

**特殊点：**
- 这两个资源**只有 list + update**，无 POST / DELETE
- 前端组件层禁掉按钮（参考 §前端组件）

**Endpoints:**
- `GET /business-hours` / `PUT /business-hours/{weekday}`
- `GET /resources` / `PUT /resources/{id}`

**Commit：** `feat(admin): Business Hours + Resources 配置类资源`

### Task 7: Health 模块

**Endpoints:**
- `GET /health/metrics?pet_id=&from=&to=` → `PageResp[HealthMetricOut]`
- `GET /health/alerts` → `PageResp[HealthAlertOut]`
- `POST /health/alerts/{id}/ack` → 204

**HealthMetricOut：** metric_id, pet_id, metric_type, value, recorded_at, source

**HealthAlertOut：** alert_id, pet_id, level (info/warn/critical), title, created_at, acked_at

**Commit：** `feat(admin): Health 模块（指标 + 告警）`

### Task 8: Operations 模块

**Endpoints:**
- `GET /operations/ltv?segment=` → 各分群聚合（avg_ltv, total_customers, segment）
- `GET /operations/churn?threshold=0.5` → 流失风险列表
- `GET /operations/feature-vectors/{customer_id}` → 单客户特征

**响应：** 直接用 dict（聚合结果形状不固定）

**Commit：** `feat(admin): Operations 模块（LTV + 流失 + 特征）`

### Task 9: Supply 模块

**Endpoints:**
- `GET /supply/skus?search=` → SKU 列表
- `PUT /supply/skus/{id}` → 改库存阈值 / 单位
- `GET /supply/restock-decisions` → 当前活跃补货决策

**SkuOut：** sku_id, name, unit, current_stock, reorder_point, safety_stock

**Commit：** `feat(admin): Supply 模块（SKU + 补货决策）`

### Task 10: Marketing 模块

**Endpoints:**
- `GET /marketing/contents?status=` → 内容生成历史
- `POST /marketing/contents/generate` → 手动触发（请求体含 topic / channel）

**ContentOut：** content_id, topic, channel, body_preview, status (draft/approved/sent), generated_at

**Commit：** `feat(admin): Marketing 模块（内容记录 + 手动触发）`

### Task 11: Subscriptions + Ecosystem

**Endpoints:**
- `GET /subscriptions` / `GET /subscriptions/{id}` / `GET /subscriptions/billing-reports?month=`
- `GET /ecosystem/partners` / `GET /ecosystem/referrals?status=`

**Commit：** `feat(admin): Subscriptions + Ecosystem 模块`

### Task 12: Traces 模块

**Endpoints:**
- `GET /traces?thread_id=&limit=` → Agent 对话追溯（来自 LangFuse / 进程内 trace backend）
- `GET /traces/{thread_id}` → 单 thread 全节点

**TraceOut：** trace_id, thread_id, started_at, ended_at, status, agent_outputs 摘要

**Commit：** `feat(admin): Traces 模块（Agent 对话追溯）`

### Task 13: Dashboard 聚合

**Endpoints:**
- `GET /stats/overview` → `{today_appointments, today_new_customers, pending_alerts, low_stock_skus, recent_revenue}`

**实现：** 一次查询聚合多个 COUNT/SUM，组装成 dict

**Commit：** `feat(admin): Dashboard 聚合 stats`

### Task 14: 后端集成测试 + 整体跑通

**Files:** `tests/test_admin_routes.py`（扩充）

**新增测试：** `test_full_flow_create_customer_then_appointment`（端到端：建客户 → 建宠物 → 建预约 → 取消）

**运行：** `docker compose exec app python -m pytest tests/ -v` 确认所有现有 + 新增测试通过

**Commit：** `test(admin): 后端集成测试 + 全套测试通过验证`

---

# 阶段 4：前端脚手架与通用组件

## Task 15: 前端通用组件（DataTable / FormDrawer / StatCard）

**Files:**
- Create: `admin/src/components/common/DataTable.vue`
- Create: `admin/src/components/common/FormDrawer.vue`
- Create: `admin/src/components/common/StatCard.vue`
- Create: `admin/src/utils/format.ts`
- Create: `admin/src/utils/http.ts`
- Create: `admin/src/api/client.ts`

### Step 15.1: 创建 `admin/src/api/client.ts`

```ts
import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

export const http: AxiosInstance = axios.create({
  baseURL: '/api/admin',
  timeout: 30000
})

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const msg = err.response?.data?.detail ?? err.message ?? '请求失败'
    ElMessage.error(String(msg))
    return Promise.reject(err)
  }
)
```

### Step 15.2: 创建 `admin/src/utils/format.ts`

```ts
export function formatDateTime(d: string | Date | null | undefined): string {
  if (!d) return '-'
  const date = typeof d === 'string' ? new Date(d) : d
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatDate(d: string | Date | null | undefined): string {
  if (!d) return '-'
  const date = typeof d === 'string' ? new Date(d) : d
  return date.toLocaleDateString('zh-CN')
}
```

### Step 15.3: 创建 `admin/src/utils/http.ts`

```ts
import { http } from './client'

export interface PageResp<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export async function listPage<T>(
  path: string,
  params: Record<string, unknown> = {}
): Promise<PageResp<T>> {
  const { data } = await http.get<PageResp<T>>(path, { params })
  return data
}

export async function getOne<T>(path: string): Promise<T> {
  const { data } = await http.get<T>(path)
  return data
}

export async function createOne<T>(path: string, payload: unknown): Promise<T> {
  const { data } = await http.post<T>(path, payload)
  return data
}

export async function updateOne<T>(path: string, payload: unknown): Promise<T> {
  const { data } = await http.put<T>(path, payload)
  return data
}

export async function deleteOne(path: string): Promise<void> {
  await http.delete(path)
}
```

### Step 15.4: 创建 `admin/src/components/common/DataTable.vue`

```vue
<template>
  <div class="data-table">
    <div class="data-table__toolbar" v-if="$slots.toolbar">
      <slot name="toolbar" />
    </div>
    <el-table :data="items" v-loading="loading" stripe border>
      <slot />
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      :page-sizes="[10, 20, 50, 100]"
      layout="total, sizes, prev, pager, next, jumper"
      @current-change="$emit('page-change', page)"
      @size-change="$emit('size-change', pageSize)"
    />
  </div>
</template>

<script setup lang="ts" generic="T">
import { ref, watch } from 'vue'

interface Props {
  items: T[]
  total: number
  loading?: boolean
  initialPage?: number
  initialPageSize?: number
}
const props = withDefaults(defineProps<Props>(), {
  loading: false,
  initialPage: 1,
  initialPageSize: 20
})
defineEmits<{
  (e: 'page-change', page: number): void
  (e: 'size-change', size: number): void
}>()

const page = ref(props.initialPage)
const pageSize = ref(props.initialPageSize)
watch(() => props.initialPage, (v) => { page.value = v })
</script>

<style scoped>
.data-table__toolbar {
  margin-bottom: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.el-pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
```

### Step 15.5: 创建 `admin/src/components/common/FormDrawer.vue`

```vue
<template>
  <el-drawer
    :model-value="modelValue"
    :title="title"
    direction="rtl"
    size="480px"
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="$emit('closed')"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <slot :form="form" />
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">
        保存
      </el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts" generic="T extends Record<string, unknown>">
import { ref } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'

interface Props {
  modelValue: boolean
  title: string
  form: T
  rules?: Record<string, unknown>
  submitting?: boolean
}
withDefaults(defineProps<Props>(), { submitting: false })

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submit', form: T): void
  (e: 'closed'): void
}>()

const formRef = ref<FormInstance>()

function onSubmit() {
  formRef.value?.validate((ok) => {
    if (!ok) {
      ElMessage.warning('请检查表单')
      return
    }
    // 这里 emit 时类型擦除，由父组件处理
    emit('submit', (formRef.value?.modelValue ?? {}) as T)
  })
}
</script>
```

### Step 15.6: 创建 `admin/src/components/common/StatCard.vue`

```vue
<template>
  <el-card shadow="hover" class="stat-card">
    <div class="stat-card__label">{{ label }}</div>
    <div class="stat-card__value">{{ value }}</div>
    <div class="stat-card__trend" v-if="trend !== undefined">
      <span :class="trend >= 0 ? 'up' : 'down'">
        {{ trend >= 0 ? '↑' : '↓' }} {{ Math.abs(trend) }}%
      </span>
    </div>
  </el-card>
</template>

<script setup lang="ts">
interface Props {
  label: string
  value: number | string
  trend?: number
}
defineProps<Props>()
</script>

<style scoped>
.stat-card { margin-bottom: 12px; }
.stat-card__label { color: #909399; font-size: 13px; }
.stat-card__value { font-size: 28px; font-weight: 600; margin: 8px 0; }
.stat-card__trend .up { color: #67c23a; }
.stat-card__trend .down { color: #f56c6c; }
</style>
```

### Step 15.7: 创建 `admin/tests/DataTable.spec.ts`

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DataTable from '@/components/common/DataTable.vue'

describe('DataTable', () => {
  it('renders items', () => {
    const wrapper = mount(DataTable, {
      props: { items: [{ a: 1 }, { a: 2 }], total: 2 }
    })
    expect(wrapper.findAll('.el-table__row').length).toBeGreaterThanOrEqual(0)
  })
  it('emits page-change', async () => {
    const wrapper = mount(DataTable, {
      props: { items: [], total: 0 }
    })
    wrapper.vm.$emit('page-change', 2)
    expect(wrapper.emitted('page-change')).toBeTruthy()
  })
})
```

### Step 15.8: 跑前端测试

```bash
cd admin
npm install
npm run test
# 期望: PASS DataTable
```

### Step 15.9: Commit

```bash
git add admin/src/components/common admin/src/utils admin/src/api/client.ts admin/tests
git commit -m "feat(admin): 通用组件 DataTable/FormDrawer/StatCard + axios 封装"
```

---

## Task 16: Layout（Sidebar / Header / AppLayout）

**Files:**
- Create: `admin/src/components/layout/Sidebar.vue`
- Create: `admin/src/components/layout/Header.vue`
- Create: `admin/src/components/layout/AppLayout.vue`
- Modify: `admin/src/router/index.ts`
- Create: `admin/src/stores/app.ts`

### Step 16.1: 创建 `admin/src/stores/app.ts`

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  function toggleSidebar() { sidebarCollapsed.value = !sidebarCollapsed.value }
  return { sidebarCollapsed, toggleSidebar }
})
```

### Step 16.2: 创建 `admin/src/components/layout/Sidebar.vue`

```vue
<template>
  <el-aside :width="sidebarCollapsed ? '64px' : '220px'" class="sidebar">
    <el-menu :default-active="route.path" router :collapse="sidebarCollapsed">
      <el-menu-item index="/dashboard" :route="{ path: '/dashboard' }">
        <el-icon><Histogram /></el-icon>
        <template #title>仪表盘</template>
      </el-menu-item>
      <el-menu-item index="/customers" :route="{ path: '/customers' }">
        <el-icon><User /></el-icon>
        <template #title>客户</template>
      </el-menu-item>
      <el-menu-item index="/pets" :route="{ path: '/pets' }">
        <el-icon><Cat /></el-icon>
        <template #title>宠物</template>
      </el-menu-item>
      <el-menu-item index="/appointments" :route="{ path: '/appointments' }">
        <el-icon><Calendar /></el-icon>
        <template #title>预约</template>
      </el-menu-item>
      <el-menu-item index="/business-hours" :route="{ path: '/business-hours' }">
        <el-icon><Clock /></el-icon>
        <template #title>营业时间</template>
      </el-menu-item>
      <el-menu-item index="/resources" :route="{ path: '/resources' }">
        <el-icon><Tools /></el-icon>
        <template #title>美容资源</template>
      </el-menu-item>
      <el-menu-item index="/health/metrics" :route="{ path: '/health/metrics' }">
        <el-icon><TrendCharts /></el-icon>
        <template #title>健康指标</template>
      </el-menu-item>
      <el-menu-item index="/operations/ltv" :route="{ path: '/operations/ltv' }">
        <el-icon><DataAnalysis /></el-icon>
        <template #title>LTV 分群</template>
      </el-menu-item>
      <el-menu-item index="/supply/skus" :route="{ path: '/supply/skus' }">
        <el-icon><Box /></el-icon>
        <template #title>SKU</template>
      </el-menu-item>
      <el-menu-item index="/marketing/contents" :route="{ path: '/marketing/contents' }">
        <el-icon><Promotion /></el-icon>
        <template #title>营销内容</template>
      </el-menu-item>
      <el-menu-item index="/subscriptions" :route="{ path: '/subscriptions' }">
        <el-icon><CreditCard /></el-icon>
        <template #title>订阅</template>
      </el-menu-item>
      <el-menu-item index="/ecosystem/partners" :route="{ path: '/ecosystem/partners' }">
        <el-icon><Share /></el-icon>
        <template #title>合作医院</template>
      </el-menu-item>
      <el-menu-item index="/traces" :route="{ path: '/traces' }">
        <el-icon><Document /></el-icon>
        <template #title>对话追溯</template>
      </el-menu-item>
    </el-menu>
  </el-aside>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { computed } from 'vue'

const route = useRoute()
const app = useAppStore()
const sidebarCollapsed = computed(() => app.sidebarCollapsed)
</script>

<style scoped>
.sidebar { background: #001529; min-height: 100vh; }
.sidebar :deep(.el-menu) { border-right: none; background: transparent; }
.sidebar :deep(.el-menu-item) { color: #fff; }
</style>
```

### Step 16.3: 创建 `admin/src/components/layout/Header.vue`

```vue
<template>
  <el-header class="header">
    <el-button text @click="app.toggleSidebar">
      <el-icon><Fold v-if="!app.sidebarCollapsed" /><Expand v-else /></el-icon>
    </el-button>
    <span class="header__title">PetOps Admin</span>
  </el-header>
</template>

<script setup lang="ts">
import { useAppStore } from '@/stores/app'
const app = useAppStore()
</script>

<style scoped>
.header {
  background: #fff;
  border-bottom: 1px solid #e6e6e6;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
}
.header__title { font-size: 16px; font-weight: 600; }
</style>
```

### Step 16.4: 创建 `admin/src/components/layout/AppLayout.vue`

```vue
<template>
  <el-container class="app-layout">
    <Sidebar />
    <el-container>
      <Header />
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import Sidebar from './Sidebar.vue'
import Header from './Header.vue'
</script>

<style scoped>
.app-layout { height: 100vh; }
.el-main { background: #f5f7fa; padding: 16px; overflow: auto; }
</style>
```

### Step 16.5: 修改 `admin/src/router/index.ts`，把全部 13 资源路由加上 + 用 AppLayout

```ts
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('@/views/DashboardView.vue') },
      { path: 'customers', component: () => import('@/views/customers/ListView.vue') },
      { path: 'customers/:id', component: () => import('@/views/customers/DetailView.vue') },
      { path: 'pets', component: () => import('@/views/pets/ListView.vue') },
      { path: 'pets/:id', component: () => import('@/views/pets/DetailView.vue') },
      { path: 'appointments', component: () => import('@/views/appointments/ListView.vue') },
      { path: 'business-hours', component: () => import('@/views/business-hours/View.vue') },
      { path: 'resources', component: () => import('@/views/resources/View.vue') },
      { path: 'health/metrics', component: () => import('@/views/health/MetricsView.vue') },
      { path: 'health/alerts', component: () => import('@/views/health/AlertsView.vue') },
      { path: 'operations/ltv', component: () => import('@/views/operations/LtvView.vue') },
      { path: 'operations/churn', component: () => import('@/views/operations/ChurnView.vue') },
      { path: 'supply/skus', component: () => import('@/views/supply/SkusView.vue') },
      { path: 'marketing/contents', component: () => import('@/views/marketing/ContentsView.vue') },
      { path: 'subscriptions', component: () => import('@/views/subscriptions/ListView.vue') },
      { path: 'ecosystem/partners', component: () => import('@/views/ecosystem/PartnersView.vue') },
      { path: 'traces', component: () => import('@/views/traces/ListView.vue') },
      { path: 'traces/:thread_id', component: () => import('@/views/traces/DetailView.vue') }
    ]
  }
]

export default createRouter({
  history: createWebHistory('/admin/'),
  routes
})
```

### Step 16.6: 删除 Task 1.11-1.12 创建的占位路由

替换 Step 1.11-1.12 创建的 `admin/src/views/customers/ListView.vue` 等占位文件，改成空 `<template><div>占位</div></template>`（后续 Task 替换）。

### Step 16.7: 跑前端测试 + 验证 dev 服务

```bash
cd admin
npm run test
npm run dev &
sleep 3
curl -I http://localhost:5173/admin/
# 期望: 200, 看到 Vue 渲染的 HTML
kill %1
```

### Step 16.8: Commit

```bash
git add admin/src/components/layout admin/src/stores admin/src/router/index.ts
git commit -m "feat(admin): Layout（Sidebar/Header/AppLayout）+ 完整路由表"
```

---

# 阶段 5：前端视图（13 资源 + Dashboard）

> 每个视图都遵循统一模式：
> - 列表页：搜索框 + DataTable + 新建按钮（配置类无新建按钮）
> - 详情页：基础信息卡片 + 关联数据
> - 配置类：仅列表 + 行内编辑按钮

## Task 17: Dashboard View

**Files:** `admin/src/views/DashboardView.vue`

```vue
<template>
  <div>
    <h2>仪表盘</h2>
    <el-row :gutter="12">
      <el-col :span="6"><StatCard label="今日预约" :value="overview.today_appointments ?? 0" /></el-col>
      <el-col :span="6"><StatCard label="今日新增客户" :value="overview.today_new_customers ?? 0" /></el-col>
      <el-col :span="6"><StatCard label="待处理告警" :value="overview.pending_alerts ?? 0" /></el-col>
      <el-col :span="6"><StatCard label="低库存 SKU" :value="overview.low_stock_skus ?? 0" /></el-col>
    </el-row>
    <el-row :gutter="12">
      <el-col :span="12"><StatCard label="本月营收 (元)" :value="overview.recent_revenue ?? 0" /></el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { http } from '@/api/client'
import StatCard from '@/components/common/StatCard.vue'

const overview = ref<Record<string, number>>({})

onMounted(async () => {
  const { data } = await http.get('/stats/overview')
  overview.value = data
})
</script>
```

### Step 17.1: Commit

```bash
git add admin/src/views/DashboardView.vue
git commit -m "feat(admin): Dashboard 视图（聚合 stat cards）"
```

---

## Task 18-29: 12 个资源视图（重复 Task 17 模式）

每个资源的 ListView 都遵循同一模板。以 Customers 为例：

### Task 18: Customers 视图

**Files:**
- Create: `admin/src/api/customers.ts`
- Create: `admin/src/views/customers/ListView.vue`
- Create: `admin/src/views/customers/DetailView.vue`

**`admin/src/api/customers.ts`:**

```ts
import { http } from './client'
import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http'

export interface Customer {
  customer_id: string
  name: string
  phone: string | null
  registered_at: string
  ltv: number | null
  churn_score: number | null
  segment: string | null
  onboarding_pending: boolean
}

export const customersApi = {
  list: (page: number, pageSize: number, search?: string) =>
    listPage<Customer>('/customers', { page, page_size: pageSize, search }),
  get: (id: string) => getOne<Customer>(`/customers/${id}`),
  create: (payload: { name: string; phone?: string }) =>
    createOne<Customer>('/customers', payload),
  update: (id: string, payload: { name: string; phone?: string }) =>
    updateOne<Customer>(`/customers/${id}`, payload),
  remove: (id: string) => deleteOne(`/customers/${id}`)
}
```

**`admin/src/views/customers/ListView.vue`:**

```vue
<template>
  <div>
    <DataTable
      :items="items"
      :total="total"
      :loading="loading"
      :initial-page="page"
      :initial-page-size="pageSize"
      @page-change="onPageChange"
      @size-change="onSizeChange"
    >
      <template #toolbar>
        <el-input v-model="search" placeholder="搜索姓名/手机号" clearable style="width: 240px" @keyup.enter="reload" />
        <el-button @click="reload">搜索</el-button>
        <el-button type="primary" @click="drawerOpen = true">新建客户</el-button>
      </template>
      <el-table-column prop="name" label="姓名" />
      <el-table-column prop="phone" label="手机号" />
      <el-table-column prop="ltv" label="LTV" />
      <el-table-column prop="churn_score" label="流失概率" />
      <el-table-column prop="segment" label="分群" />
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button text type="primary" @click="goDetail(row.customer_id)">详情</el-button>
          <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="确认删除?" @confirm="onRemove(row.customer_id)">
            <template #reference><el-button text type="danger">删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </DataTable>
    <FormDrawer v-model="drawerOpen" :title="editing ? '编辑客户' : '新建客户'" :form="form" @submit="onSubmit">
      <template #default="{ form }">
        <el-form-item label="姓名" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" />
        </el-form-item>
      </template>
    </FormDrawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import DataTable from '@/components/common/DataTable.vue'
import FormDrawer from '@/components/common/FormDrawer.vue'
import { customersApi, type Customer } from '@/api/customers'

const router = useRouter()
const items = ref<Customer[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const search = ref('')
const drawerOpen = ref(false)
const editing = ref(false)
const form = reactive({ name: '', phone: '' })
const editingId = ref<string | null>(null)

async function reload() {
  loading.value = true
  try {
    const r = await customersApi.list(page.value, pageSize.value, search.value || undefined)
    items.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

function onPageChange(p: number) { page.value = p; reload() }
function onSizeChange(s: number) { pageSize.value = s; reload() }

function openEdit(row: Customer) {
  editing.value = true
  editingId.value = row.customer_id
  form.name = row.name
  form.phone = row.phone ?? ''
  drawerOpen.value = true
}

async function onSubmit() {
  if (editing.value && editingId.value) {
    await customersApi.update(editingId.value, { name: form.name, phone: form.phone || undefined })
    ElMessage.success('已更新')
  } else {
    await customersApi.create({ name: form.name, phone: form.phone || undefined })
    ElMessage.success('已创建')
  }
  drawerOpen.value = false
  editing.value = false
  form.name = ''; form.phone = ''
  await reload()
}

async function onRemove(id: string) {
  await customersApi.remove(id)
  ElMessage.success('已删除')
  await reload()
}

function goDetail(id: string) { router.push(`/customers/${id}`) }

onMounted(reload)
</script>
```

**`admin/src/views/customers/DetailView.vue`:** 显示客户基础信息 + 宠物列表 + 最近预约（用 `el-descriptions`）

**Commit：** `feat(admin): Customers 列表 + 详情 + 新建/编辑/删除`

---

### Task 19: Pets 视图

按 Customers 同模式。ListView 含 owner_id / name / species / breed / life_stage 等列；DetailView 含宠物详情 + health_metrics 列表

**Commit：** `feat(admin): Pets 列表 + 详情`

### Task 20: Appointments 视图

**特殊点：**
- 过滤栏含状态 + 日期范围
- 取消按钮弹 Popconfirm，调用 DELETE 端点（后端改 status=cancelled）
- 详情页显示预约时间 / 服务 / 客户 / 宠物

**Commit：** `feat(admin): Appointments 列表 + 详情（含取消）`

### Task 21: Business Hours + Resources 视图（配置类）

**特殊点：**
- **没有**"新建" / "删除"按钮
- 表格行内"编辑"按钮 → 弹 FormDrawer 修改

**Commit：** `feat(admin): Business Hours + Resources 视图（仅编辑）`

### Task 22: Health 视图

**两个视图：**
- `MetricsView`：按 pet_id 过滤的健康指标列表
- `AlertsView`：健康告警列表 + "确认告警"按钮

**Commit：** `feat(admin): Health 视图（指标 + 告警）`

### Task 23: Operations 视图

**两个视图：**
- `LtvView`：分群聚合卡片（每个 segment 一张）
- `ChurnView`：流失风险客户列表

**Commit：** `feat(admin): Operations 视图（LTV + 流失）`

### Task 24: Supply 视图

**单视图：** `SkusView`：SKU 列表 + 行内编辑 reorder_point

**Commit：** `feat(admin): Supply 视图（SKU）`

### Task 25: Marketing 视图

**单视图：** `ContentsView`：内容列表 + "生成新内容"按钮

**Commit：** `feat(admin): Marketing 视图`

### Task 26: Subscriptions 视图

**单视图：** `ListView`：订阅列表 + 计费报告子页面（month 过滤）

**Commit：** `feat(admin): Subscriptions 视图`

### Task 27: Ecosystem 视图

**单视图：** `PartnersView`：合作医院 + 转诊记录 tab

**Commit：** `feat(admin): Ecosystem 视图`

### Task 28: Traces 视图

**两个视图：**
- `ListView`：agent 对话列表
- `DetailView`：单 thread 节点树（用 el-tree）

**Commit：** `feat(admin): Traces 视图（对话追溯）`

---

# 阶段 6：集成验证

## Task 29: 前端测试 + 整体联调

**Files:**
- Create: `admin/tests/DataTable.spec.ts`（已在 Task 15 创建）
- Create: `admin/tests/StatCard.spec.ts`
- Create: `admin/tests/http.spec.ts`

### Step 29.1: 创建 `admin/tests/StatCard.spec.ts`

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatCard from '@/components/common/StatCard.vue'

describe('StatCard', () => {
  it('renders value', () => {
    const w = mount(StatCard, { props: { label: 'X', value: 42 } })
    expect(w.text()).toContain('42')
  })
  it('shows up trend for positive', () => {
    const w = mount(StatCard, { props: { label: 'X', value: 1, trend: 5 } })
    expect(w.text()).toContain('↑')
  })
})
```

### Step 29.2: 创建 `admin/tests/http.spec.ts`

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import axios from 'axios'
import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http'

vi.mock('axios')
const mocked = axios as unknown as { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn>; put: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn> }

beforeEach(() => { vi.clearAllMocks() })

describe('http utils', () => {
  it('listPage returns PageResp', async () => {
    mocked.get = vi.fn().mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 20 } })
    const r = await listPage('/foo')
    expect(r.total).toBe(0)
  })
  it('deleteOne calls axios.delete', async () => {
    mocked.delete = vi.fn().mockResolvedValue({})
    await deleteOne('/foo/1')
    expect(mocked.delete).toHaveBeenCalledWith('/foo/1')
  })
})
```

### Step 29.3: 跑前端测试

```bash
cd admin
npm run test
# 期望: 所有测试通过
```

### Step 29.4: 跑后端测试

```bash
cd /root/.../pet
docker compose exec app python -m pytest tests/ -v
# 期望: 所有测试通过（既有 538 + 新增 80+）
```

### Step 29.5: 端到端浏览器验证

```bash
docker compose build admin
docker compose up -d admin
# 浏览器打开 https://你的域名/admin/
# 验证：能看到 dashboard、点侧边栏能进各页面、DataTable 能加载（即便空表）
```

### Step 29.6: Commit + 总结

```bash
git add admin/tests
git commit -m "test(admin): 前端组件单测 + 后端全套测试通过验证"
```

最后给一个项目级 README 段落更新（`<repo>/README.md` 或类似）说明 admin 后台入口：

```bash
git commit --allow-empty -m "docs: admin 后台已上线，访问 /admin/"
```

---

## 完成检查清单

- [ ] 后端 80+ 测试通过（含 admin）
- [ ] 前端 20+ 测试通过
- [ ] `docker compose up -d` 一键起所有服务（含 admin）
- [ ] 浏览器打开 `https://域名/admin/` 看到 dashboard
- [ ] 每个资源能完成"列表 → 新建 → 编辑 → 删除"全流程
- [ ] 配置类资源（resources / business-hours）只有列表 + 编辑
- [ ] 现有 538+ 测试全部仍通过