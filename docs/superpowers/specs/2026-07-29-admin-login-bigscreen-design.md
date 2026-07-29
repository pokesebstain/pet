# Admin 登录 + 大屏 设计

> 日期：2026-07-29
> 类型：功能扩展
> 状态：已批准 / 实施中

## 目标

1. **登录**：硬编码账号密码 + token，给 admin 后台加访问控制
2. **大屏**：`/bigscreen` 独立路由（公开），店内电视展示用，5 个核心数字 + 服务分布 + 热门宠物 TOP 5

## 范围

- **登录**：单用户硬编码（.env 预置 username + bcrypt 密码 + token）
- **大屏内容**（4 个板块，2 选 1）：核心数字（必选）+ 服务分布 + 热门宠物（可选板块）
- **大屏路由**：`/bigscreen` 独立路由（不需登录，公开）
- **实时性**：30 秒轮询（不引入 WebSocket）

## 技术

- **后端**：`secrets.token_urlsafe` 生成 token + `bcrypt` 验证密码 + FastAPI 依赖
- **前端**：`Pinia` auth store + 路由守卫 + `echarts` 5
- **不引入**：JWT 库、Session 中间件

## API 设计

### 登录端点

```
POST /api/admin/login
  Body: {"username": "admin", "password": "xxx"}
  Resp 200: {"token": "...", "username": "admin"}
  Resp 401: {"detail": "用户名或密码错误"}

GET /api/admin/me
  Header: Authorization: Bearer <token>
  Resp 200: {"username": "admin"}
  Resp 401: {"detail": "未登录或 token 失效"}

POST /api/admin/logout
  # 无状态，前端清 token 即可
```

### 大屏数据端点

```
GET /api/admin/stats/bigscreen   (公开)
  Resp 200: {
    "today_appointments": 12,
    "today_new_customers": 3,
    "month_revenue": 18400.50,
    "pending_alerts": 2,
    "low_stock_skus": 1,
    "service_distribution": {"grooming": 60, "medical_bath": 25, "beauty": 15},
    "top_pets": [
      {"name": "绒绒", "visits": 12},
      ...
    ],
    "generated_at": "2026-07-29T14:23:45Z"
  }
```

## 前端设计

### 新增文件

```
admin/src/
├── views/
│   ├── LoginView.vue          # 登录页
│   └── BigscreenView.vue      # 大屏
├── stores/
│   └── auth.ts                # 存 token + user
└── api/
    └── auth.ts                # login / logout / me / bigscreen
```

### 路由变更

```ts
const routes = [
  { path: '/login', component: () => import('@/views/LoginView.vue') },  // 新
  { path: '/bigscreen', component: () => import('@/views/BigscreenView.vue') },  // 新（独立）
  // 其它路由加 meta: { requiresAuth: true }
]

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.token) return { path: '/login' }
})
```

### 大屏布局

```
┌────────────────────────────────────────────────────┐
│ PetOps 实时大屏 | 2026-07-29 周三 14:23:45         │  顶部
├────────────────────────────────────────────────────┤
│  今日预约  │ 今日新客 │ 本月营收  │ 待处理  │ 低库存 │  5 大数字
│    12    │    3    │ ¥18,400 │    2    │    1    │
├──────────────────────────┬───────────────────────────┤
│   服务分布（饼图）        │  热门宠物 TOP 5         │
│   洗护 60% / 药浴 25% / 美容 15% │  1. 绒绒 12次 │
│                          │  2. 豆豆  9次         │
└──────────────────────────┴───────────────────────────┘
```

- 全黑背景 `#0a0e27` + 渐变高亮色 `#00f2ff` / `#3a7bd5`
- 数字用 `requestAnimationFrame` 滚动动画（0 → 实际值）
- 30 秒自动轮询 + 切换 tab 不轮询

## 环境变量更新

```bash
# .env.template 新增
PETOPS_ADMIN_USERNAME=admin
PETOPS_ADMIN_PASSWORD=<明文密码，启动时 bcrypt 校验；首次启动检测不到会自动生成 token 到 .env>
PETOPS_ADMIN_TOKEN=<启动时生成 64 字节 url-safe token>
```

## 排期

| 阶段 | 内容 | 估计 |
|------|------|------|
| 1 | 后端：3 个登录端点 + 大屏聚合端点 + .env 模板 | 1 小时 |
| 2 | 前端：LoginView + auth store + 路由守卫 | 1 小时 |
| 3 | 前端：BigscreenView + ECharts 集成 + 30s 轮询 | 1.5 小时 |
| 4 | 测试 + 端到端验证 | 0.5 小时 |

**总：4 小时**

## 不做

- 真实用户表（硬编码足够）
- 多角色 / RBAC
- 密码重置 / 邮箱验证
- 登录失败锁定（防爆破可后续加）
- WebSocket 实时推送
- 大屏内容编辑器
