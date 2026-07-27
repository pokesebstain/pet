# Implementation Plan: PetOps 智能宠物店运营大脑平台

## Overview

本实现计划基于已批准的 `design.md` 与 `requirements.md`，采用增量、测试驱动的方式落地 PetOps 平台。技术栈为 **Python + FastAPI + LangGraph + LangChain**，数据层为 **PostgreSQL（RLS）+ pgvector + TimescaleDB**，事件总线为 **Redis Stream**，属性测试库为 **hypothesis**。

**范围约束（重要）**：
- 模型微调**不在本次范围**。Text2SQL 与意图分类/路由均通过**云端 LLM（通义千问 / 智谱 GLM）**结合提示工程与少样本实现，不引入 Qwen2.5-7B + LoRA / LLaMA-Factory / vLLM 微调模型。
- 视觉健康检测**仅**通过**第三方 API（宠智灵 / 百目魔君）**在 `Vision_Provider` 抽象层之后实现，不实现自研 / 微调 YOLO/ViT 视觉模型。

实现顺序遵循"由内向外"：先搭建基础设施与数据模型 → 纯函数算法层（可独立验证）→ 特征存储与工具层 → 云端 LLM / RAG / Text2SQL → 事件总线 → 业务引擎 → AI 决策中枢与 HITL → 视觉与可观测 → 端到端集成。每个算法与关键不变量都配有对应的属性测试子任务。

## Tasks

- [ ] 1. 搭建项目结构、配置与核心数据模型
  - [x] 1.1 初始化项目骨架与依赖
    - 创建包目录结构：`app/`（core、models、tools、agents、engines、events、rag、vision、observability）、`tests/`
    - 配置依赖：fastapi、uvicorn、pydantic、sqlalchemy/psycopg、langgraph、langchain、redis、hypothesis、pytest
    - 建立配置加载模块（读取数据库、Redis、LLM、视觉 API 等配置，支持按环境切换）
    - 建立 pytest 与 hypothesis 测试脚手架
    - _Requirements: 5.1, 20.1_

  - [x] 1.2 定义核心 Pydantic 数据模型与字段校验
    - 实现 `Tenant`、`Customer`、`Pet`、`LifeStage`、`HealthMetric`、`DomainEvent`、`KnowledgeChunk`、`FeatureVector`、`Subscription`、`SKU`、`DemandForecast` 等模型
    - 实现字段校验：`churn_score ∈ [0,1]`、`ltv ≥ 0`、`weight_kg > 0`、`birth_date ≤ now`、所有实体 `tenant_id` 非空
    - _Requirements: 5.3, 6.1, 7.1, 9.2_

  - [ ]* 1.3 编写数据模型校验的单元测试
    - 覆盖各字段边界与非法值（负体重、越界分数、空 tenant_id 等）
    - _Requirements: 5.3, 9.2_

- [ ] 2. 建立数据库 Schema、RLS 与时序 / 向量扩展
  - [x] 2.1 创建 PostgreSQL Schema 与行级安全（RLS）策略
    - 为所有携带 `tenant_id` 的表建表并启用 RLS，策略基于会话变量 `app.current_tenant`
    - 建立 TimescaleDB 超表（health_metrics）与 pgvector 表（knowledge_chunks，含 embedding 向量列）
    - 提供数据库迁移脚本与初始化逻辑
    - _Requirements: 5.1, 5.2, 9.1, 16.1_

  - [x] 2.2 实现 RLS 会话上下文管理器
    - 实现连接/会话级 `tenant_id` 注入（进入时 `SET LOCAL app.current_tenant`，退出时清理）
    - 上下文缺失或 `tenant_id` 为空时抛出租户上下文缺失错误
    - _Requirements: 5.1, 5.4_

  - [ ]* 2.3 编写 RLS 跨租户隔离渗透测试
    - 以租户 A 上下文查询租户 B 数据，断言零返回
    - _Requirements: 5.2, 5.5_

- [ ] 3. 实现纯函数算法层（生命阶段、流失、LTV）
  - [x] 3.1 实现生命阶段判定 `judge_life_stage`
    - 加载物种/品种体型分级表与阈值表；实现 PUPPY/ADULT/SENIOR 判定
    - 处理未收录品种回退到物种默认阈值；非法/缺失参数（age 越界、缺物种/品种、不支持物种）抛参数无效错误
    - 保证大型犬 SENIOR 阈值 ≤ 小型犬阈值
    - _Requirements: 10.1, 10.2, 10.3, 10.5, 10.6_

  - [ ]* 3.2 编写生命阶段判定的属性测试
    - **Property 4: 生命阶段完备性** — ∀ (species, breed, age∈[0,360]) 必返回三值之一，且随 age 递增单调不回退，大型犬 SENIOR 阈值 ≤ 小型犬
    - **Validates: Requirements 10.1, 10.2, 10.4**
    - 使用 hypothesis 生成随机物种/品种/月龄

  - [x] 3.3 实现流失预测 `predict_churn`
    - 实现特征归一化循环（不变式：已处理特征落在 [0,1]）与打分，clamp 到 [0,1]
    - 空特征向量或缺失 RFM 必需项/越界特征时抛错
    - 保证活跃度越高 churn_score 单调不增
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 3.4 编写流失预测的属性测试
    - **Property 2: 流失分数有界** — ∀ 客户 c，`predict_churn(c) ∈ [0,1]`
    - **Validates: Requirements 7.1, 7.2**
    - 附加验证活跃度单调不增性质

  - [x] 3.5 实现 LTV 预测 `predict_ltv`
    - 基于特征与复用 `predict_churn` 的留存概率，按月累加折现（不变式：ltv ≥ 0）
    - `horizon_months` 越界（≤0、>120、非整数）抛参数无效错误；客户不存在或数据不足抛错
    - _Requirements: 6.1, 6.2, 6.3, 6.6_

  - [ ]* 3.6 编写 LTV 预测的属性测试
    - **Property 3: LTV 非负与单调** — ∀ 客户 c 与 h₁<h₂，`predict_ltv(c,h₁) ≤ predict_ltv(c,h₂)` 且均 ≥ 0
    - **Validates: Requirements 6.1, 6.2**

- [ ] 4. 实现纯函数算法层（需求预测、安全库存、推荐）
  - [x] 4.1 实现需求预测 `forecast_demand`
    - 实现季节性+趋势模型；历史 <30 天回退移动平均并标记降级；无历史抛错
    - `horizon_days` 越界（≤0、>365、非整数）抛参数无效错误；保证 demand ≥ 0、confidence ∈ [0,1]
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [ ]* 4.2 编写需求预测的属性测试
    - **Property 6: 需求预测非负** — ∀ SKU 与 horizon∈(0,365]，`predicted_demand ≥ 0` 且 `confidence ∈ [0,1]`
    - **Validates: Requirements 11.1**

  - [x] 4.3 实现安全库存与再订货点 `safety_stock`
    - 用 `inverse_normal_cdf(service_level)` 计算 z 值，`ss = z·σ_d·√L`，clamp ≥ 0；计算再订货点 ≥ ss
    - 参数越界（service_level∉(0,1)、lead_time∉(0,365]、avg_daily_demand<0）抛参数无效错误
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [ ]* 4.4 编写安全库存的属性测试
    - **Property 5: 安全库存单调性** — ∀ SKU，`service_level` 增大时 `safety_stock` 不减且恒 ≥ 0
    - **Validates: Requirements 12.1, 12.2**
    - 附加验证再订货点 ≥ 安全库存（_Requirements: 12.3_）

  - [x] 4.5 实现推荐规则引擎 `recommend`
    - 结合生命阶段/健康/流失/库存生成候选，过滤缺货 SKU，按 score 降序（并列按 SKU 升序稳定排序），限 20 条，附 `reason`
    - 客户 `tenant_id` 与上下文不符时抛越权错误；无候选返回空列表
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [ ]* 4.6 编写推荐引擎的属性测试
    - **Property 7: 推荐有序且有货** — 返回列表按 score 降序、不含缺货 SKU、每条附可解释理由
    - **Validates: Requirements 13.1, 13.2, 13.3**

- [x] 5. Checkpoint - 确保算法层全部测试通过
  - 确保所有测试通过，如有疑问请询问用户。

- [ ] 6. 实现特征存储 Feature Store
  - [x] 6.1 实现 Feature Store 读写接口与在线/离线通道
    - 实现 `write`、`get`、`get_online`（Redis 在线通道，目标 <100ms）；保证在线/离线同一特征值一致
    - 缺失特征时使用默认值并打标、触发离线回填、不中断请求；Redis 不可用降级到离线通道
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5_

  - [ ]* 6.2 编写 Feature Store 单元测试
    - 覆盖在线/离线一致性、缺失默认值打标、Redis 降级路径
    - _Requirements: 19.3, 19.4, 19.5_

- [ ] 7. 实现统一工具层（Tool Layer）基础与租户隔离
  - [x] 7.1 实现工具层基础框架与 tenant_id 强制注入
    - 定义 `@tool` 封装的调用入口，所有数据访问工具强制经 RLS 上下文注入 `tenant_id`
    - 实现结果集租户校验：任一记录 `tenant_id` ≠ 上下文则阻断并报隔离违规；结果 >1000 行截断并标记
    - 上下文缺失/空 tenant_id 拒绝调用并报错
    - _Requirements: 5.1, 5.2, 5.4, 5.5, 2.7_

  - [ ]* 7.2 编写工具层租户隔离属性测试
    - **Property 1: 租户隔离** — ∀ 查询 q，结果集中每条记录 `tenant_id` = 上下文 `tenant_id`
    - **Validates: Requirements 1.5, 2.1, 5.1, 5.2, 5.3, 13.4**

  - [x] 7.3 实现敏感数据脱敏工具
    - 对手机号/身份证号/银行卡号在展示与存储时进行中间字符掩码
    - _Requirements: 20.3, 20.6_

  - [ ]* 7.4 编写脱敏属性测试
    - **Property 13: 敏感数据脱敏** — ∀ 含敏感字段的展示/存储，敏感字段必被脱敏
    - **Validates: Requirements 20.3**

- [ ] 8. 实现云端 LLM 客户端与降级 / 熔断
  - [x] 8.1 实现 Cloud_LLM 客户端（通义千问 / 智谱 GLM）
    - 封装提示工程 / 少样本调用接口，统一超时（10s）与错误类型
    - 实现指数退避重试（初始 1s、翻倍、上限 8s、最多 3 次），重试耗尽降级受限模板查询
    - 实现熔断：60s 内连续失败 5 次触发熔断，其后 30s 直接降级；受限模板无法匹配返回重述提示
    - _Requirements: 20.1, 20.4, 20.5_

  - [ ]* 8.2 编写 LLM 客户端降级 / 熔断单元测试
    - 模拟超时、限流、连续失败，验证退避、降级与熔断状态机
    - _Requirements: 20.1, 20.4, 20.5_

- [ ] 9. 实现 Text2SQL 工具与 SQL 安全校验
  - [x] 9.1 实现基于 Cloud_LLM 的 Text2SQL 生成
    - 通过 Cloud_LLM 结合提示工程/少样本，基于固定 Schema 生成只读 SQL（30s 内）
    - _Requirements: 2.1_

  - [x] 9.2 实现 SQL 三重校验与执行控制
    - 实现 SQL 白名单、只读约束、RLS 三重校验，全部通过才执行；任一失败拒绝、无数据库变更、返回澄清并回退受限模板查询
    - 查询超过 30s 终止且无变更返回超时错误；结果 >1000 行截断标记
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 20.2_

  - [ ]* 9.3 编写 Text2SQL 安全校验属性测试
    - **Property 11: Text2SQL 安全校验** — ∀ 被执行的 SQL 必通过白名单、只读与 RLS 校验，违反者被拒绝并回退
    - **Validates: Requirements 2.2, 2.3, 20.2**

- [ ] 10. 实现 pgvector RAG 检索
  - [x] 10.1 实现 RAG_Retriever 检索与租户可见性
    - 基于 pgvector 相似度检索，范围为当前租户私有 + 平台级共享（tenant_id 为空）知识，返回降序、不低于阈值、最多 5 条（5s 内）
    - 上下文缺失/空 tenant_id 拒绝检索并报错；无匹配片段返回无匹配提示
    - _Requirements: 16.1, 16.3, 16.4, 16.5_

  - [ ]* 10.2 编写 RAG 租户可见性属性测试
    - **Property 12: RAG 检索租户可见性** — ∀ 检索结果，每片段 `tenant_id ∈ {上下文 tenant_id, None}`
    - **Validates: Requirements 16.1, 16.3**

- [ ] 11. 实现事件驱动架构（Redis Stream）
  - [x] 11.1 实现事件总线发布与多消费者分发
    - 实现 `DomainEvent` 发布；分发给 Agent 触发器、特征更新、通知推送、审计日志四类消费者（2s 内，至少一次投递）
    - _Requirements: 18.1_

  - [x] 11.2 实现消费失败重试与死信队列（DLQ）
    - 消费失败以指数退避最多重试 3 次；仍失败转 DLQ 保留原始内容并 60s 内告警
    - _Requirements: 18.4, 18.5_

  - [ ]* 11.3 编写事件总线集成测试
    - 验证发布-多消费者分发、重试、DLQ 转入与告警链路
    - _Requirements: 18.1, 18.4, 18.5_

- [x] 12. Checkpoint - 确保工具 / LLM / RAG / 事件层测试通过
  - 确保所有测试通过，如有疑问请询问用户。

- [ ] 13. 实现业务引擎：LTV 引擎与流失运营
  - [x] 13.1 实现 LTV_Engine（预测与分层）
    - 封装 `compute_ltv`（10s 内，参数校验复用 3.5）；实现 `segment_customers` 基于 LTV 与 Churn_Score 将每客户分到 高价值/成长/流失风险 恰好一个分层
    - 保证 LTV 更高且 Churn_Score 更低者分层不低于对方
    - _Requirements: 6.1, 6.4, 6.5_

  - [ ]* 13.2 编写分层单调性单元测试
    - 验证分层唯一性与单调性（6.4, 6.5）
    - _Requirements: 6.4, 6.5_

- [ ] 14. 实现业务引擎：订阅引擎与计费
  - [x] 14.1 实现 Subscription_Engine 套餐管理与计费周期
    - 实现 `create_plan`（校验计费周期与金额范围，5s 内返回套餐 ID；校验失败拒绝并报错）
    - 实现 `run_billing_cycle` 对 active 订阅生成计费、返回成功/失败/原因报告；单笔失败跳过不改状态并记录
    - 扣费成功发布 `subscription_billed` 事件
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.6_

  - [ ]* 14.2 编写订阅引擎单元测试
    - 覆盖套餐校验、计费报告、单笔失败隔离
    - _Requirements: 8.2, 8.4_

- [ ] 15. 实现业务引擎：健康数据中台与预警
  - [x] 15.1 实现 Health_Data_Hub 数据写入与事件发布
    - 校验数据（tenant_id 非空、数值范围），通过则写入 TimescaleDB 超表并发布 `health_data_ingested`（5s 内）；校验失败拒绝写入、不发事件、返回错误
    - _Requirements: 9.1, 9.2_

  - [x] 15.2 实现健康异常趋势检测（事件触发）
    - 消费 `health_data_ingested`，基于最近 30 天时序检测异常（如 7 天体重降幅 >10%，30s 内）
    - 检测到异常发布带级别（低/中/高）的 `health_alert` 并生成预警任务
    - _Requirements: 9.3, 9.4_

  - [ ]* 15.3 编写健康检测单元测试
    - 覆盖校验拒绝、异常趋势判定与 alert 级别
    - _Requirements: 9.2, 9.4_

- [ ] 16. 实现业务引擎：供应链引擎装配
  - [x] 16.1 装配 Supply_Chain_Engine 对外接口
    - 将 `forecast_demand` / `safety_stock`（算法层）封装为引擎方法，接入 TimescaleDB 销量查询与 SKU 数据
    - _Requirements: 11.1, 12.1, 12.3_

  - [ ]* 16.2 编写供应链引擎集成测试
    - 覆盖补货判定流程（预测+安全库存 vs 当前库存）
    - _Requirements: 11.1, 12.3_

- [ ] 17. 实现业务引擎：生态合作网络与转介绍
  - [x] 17.1 实现 Ecosystem_Network 转介绍动作构造与写入
    - 收到高级别 `health_alert` 构造转介绍动作（含医院、客户、宠物、原因）提交 HITL_Checkpoint（5s 内），确认前不写入
    - 批准后执行写入并发布转介绍事件；客户/宠物 tenant 不符拒绝并报越权；无可匹配医院拒绝并提示
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [ ]* 17.2 编写转介绍单元测试
    - 覆盖越权拒绝、无合作方拒绝、确认前不写入
    - _Requirements: 14.4, 14.5_

- [ ] 18. 实现营销 / 社区内容生成
  - [x] 18.1 实现 Marketing_Agent 内容生成（Cloud_LLM + RAG）
    - 结合 Cloud_LLM 与 RAG_Retriever 检索片段在当前租户+共享范围生成内容（30s 内）
    - 缺 tenant_id 拒绝并报错；LLM 超时/不可用返回失败提示；需参考但无检索片段返回缺片段提示
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [ ]* 18.2 编写内容生成单元测试
    - 覆盖缺 tenant、LLM 失败、无片段三类错误路径
    - _Requirements: 15.3, 15.4, 15.5_

- [x] 19. Checkpoint - 确保业务引擎测试通过
  - 确保所有测试通过，如有疑问请询问用户。

- [ ] 20. 实现视觉健康检测（第三方 API）
  - [x] 20.1 实现 Vision_Provider 抽象与第三方实现
    - 定义 `VisionProvider` 协议与 `get_vision_provider` 工厂；实现 `ThirdPartyVision`（宠智灵/百目魔君），业务代码不感知底层来源
    - 校验图像（JPEG/PNG、≤10MB、非缺失），通过则 30s 内返回含检测项与置信度 [0,1] 的结果；非法/缺失图像拒绝且不调 API
    - API 不可用/超时切换备用 provider 或最多 3 次重试排队；重试耗尽标记待人工复核并保留原图
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5_

  - [ ]* 20.2 编写视觉检测单元测试（Mock 第三方 API）
    - 覆盖图像校验、超时重试、耗尽后人工复核标记
    - _Requirements: 17.3, 17.4, 17.5_

- [ ] 21. 实现 AI 决策中枢：Supervisor 与专家 Agent
  - [x] 21.1 实现 AgentState 与 Supervisor 意图识别 / 路由 / 反思 / 聚合
    - 实现 `AgentState`（TypedDict，含 tenant_id、messages、intent、plan、agent_outputs、pending_action、final_answer）
    - 用 Cloud_LLM 提示工程/少样本识别意图（10s 内）并规划；路由到五类 Agent 或聚合；处理前校验 tenant_id 非空，缺失拒绝并报错
    - 低置信度/无法归类时拒绝路由并请澄清；反思循环上限 5 次，达上限进入聚合并标记部分完成
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 21.2 实现五个专家 Agent（Analysis/Operation/Health/Supply/Marketing）
    - 每个 Agent 仅经工具层访问数据/模型；接线到已实现的算法层、Text2SQL、预测、RAG、供应链等工具
    - Analysis_Agent 返回结果集+至少一条洞察（非空）/空结果说明
    - _Requirements: 2.4, 2.5_

  - [ ]* 21.3 编写 Supervisor 路由与反思分支单元测试
    - 覆盖五类路由、缺 tenant 拒绝、低置信度澄清、重规划上限部分完成
    - _Requirements: 1.6, 1.7, 1.8_

- [ ] 22. 实现多轮有状态 What-if 与 HITL 检查点
  - [x] 22.1 实现 thread_id 状态持久化与多轮加载
    - 构建 `build_supervisor_graph` 使用 checkpointer 按 thread_id 持久化/加载状态；无状态则以空会话初始化
    - 实现 Operation_Agent What-if 模拟：基于持久化上轮结果返回召回率 [0,1] 与 GMV ≥ 0；无上轮结果拒绝并提示
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 22.2 编写多轮状态一致性属性测试
    - **Property 9: 多轮状态一致** — 同一 thread_id 连续调用，后续轮次可访问前序持久化状态
    - **Validates: Requirements 3.1, 3.3**

  - [x] 22.3 实现 HITL 检查点中断 / 恢复
    - 规划含副作用（计费/推送/转介绍写入）时在检查点 interrupt，展示动作类型/目标/影响范围，批准前不执行
    - 批准执行并发布事件；拒绝取消不改数据；超过 300s 超时取消不改数据；取消记审计日志并通知
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 8.5_

  - [ ]* 22.4 编写副作用需批准属性测试
    - **Property 8: 副作用需批准** — ∀ 副作用动作必先经 HITL 批准后才执行
    - **Validates: Requirements 4.1, 4.2, 4.3, 8.3, 14.1**

- [ ] 23. 实现可观测性（Observability）与决策追溯
  - [x] 23.1 集成 LangSmith / LangFuse 决策链追溯
    - 为 Supervisor 与各 Expert_Agent 决策留存 trace（关联 trace ID、输入、各 Agent 标识、各节点输出与起止时间戳）
    - 配置追溯记录保留 ≥ 180 天
    - _Requirements: 18.2, 18.3_

  - [ ]* 23.2 编写事件可追溯属性测试
    - **Property 10: 事件可追溯** — ∀ Agent 决策链，均留有完整 trace
    - **Validates: Requirements 18.2**

- [ ] 24. 端到端集成与接线（API Gateway / BFF）
  - [x] 24.1 实现 FastAPI 路由、认证与 RLS 上下文注入
    - 实现 BFF 路由，将请求 `tenant_id` 注入 RLS 上下文并转发到业务后端与 Supervisor
    - 接线业务引擎、事件总线、工具层、AI 中枢，消除孤立组件
    - _Requirements: 1.1, 5.1_

  - [ ]* 24.2 编写端到端集成测试
    - 多轮 What-if（thread_id 状态持久化）、HITL 中断/恢复、事件发布-消费-DLQ、RLS 跨租户渗透
    - _Requirements: 3.1, 4.1, 5.2, 18.1_

- [x] 25. 最终 Checkpoint - 确保全部测试通过
  - 确保所有测试通过，如有疑问请询问用户。

- [ ] 26. 企业微信预约模块：数据模型、Schema 与排期引擎
  - [x] 26.1 定义预约模块数据模型与字段校验
    - 实现 `ServiceType`、`AppointmentStatus`、`BusinessHours`、`GroomingResource`、`TimeSlot`、`Appointment`、`BookingIntent`、`BookingRequest`、`BookingOutcome`（对应设计 14.4）
    - 校验：`TimeSlot` 满足 `capacity ≥ 0`、`0 ≤ booked_count ≤ capacity`、`start_at < end_at`；`Appointment.start_at < end_at`；`BusinessHours.open_time < close_time`；`BookingIntent.confidence ∈ [0,1]`；所有实体 `tenant_id` 非空
    - _Requirements: 21.4, 22.6, 24.2_

  - [x] 26.2 创建预约相关表与 RLS 策略
    - 为 `appointments`、`business_hours`、`grooming_resources` 建表并启用 RLS（基于会话变量 `app.current_tenant`）
    - 为防超卖建立并发约束：时段容量行（供 `SELECT … FOR UPDATE`）与按 `resource_id + 重叠时段` 的排他约束
    - _Requirements: 22.2, 24.1, 24.2_

  - [x] 26.3 实现排期引擎可用性检查与备选建议
    - 实现 `SchedulingEngine.check_availability`（营业时间判定 + 容量−已订，`available ≥ 0`）与 `get_day_schedule`
    - 实现 `suggest_alternatives`：返回至多 N 个 `available > 0` 且在营业时间内的时段，按与期望时间接近度升序（同天优先）；搜索期内无可用返回空列表
    - _Requirements: 22.1, 22.4, 23.1, 23.2, 23.3_

  - [x] 26.4 实现原子预约 `book_appointment`（防双重预订）
    - 事务内以时段容量行行级锁串行化"检查—写入"；营业时间外/满档/租户越权/时间区间无效时抛错且无任何写入
    - 写入成功保证 `booked_count ≤ capacity`；成功后发布 `appointment_booked` 事件；满档发布 `appointment_rejected_full`
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.6, 23.4, 24.1, 24.3_

  - [ ]* 26.5 编写"绝不超容量"与并发安全属性测试
    - **Property 14: 预约绝不超容量** — ∀ 时段，{PENDING,CONFIRMED} 重叠预约数 ≤ capacity，含并发争抢仅一笔成功
    - **Validates: Requirements 22.2, 22.4, 24.1**

  - [ ]* 26.6 编写自动预约营业时间与备选可用属性测试
    - **Property 15: 自动预约在营业时间内** — ∀ 自动创建预约，其 [start,end] ⊆ 营业时间
    - **Property 16: 备选建议真实可用** — ∀ 备选时段 available>0 且在营业时间内，按接近度升序、数量 ≤ N
    - **Validates: Requirements 22.1, 22.3, 23.1, 23.2**

- [ ] 27. 企业微信预约模块：入站网关、接待预约 Agent 与工具接线
  - [x] 27.1 实现企业微信入站网关 WeCom_Gateway
    - 实现回调验签/解密、消息还原、`tenant_id`/`thread_id` 注入并转发 Supervisor；验签失败拒绝且不进入决策中枢；按 `msg_id` 幂等去重
    - _Requirements: 21.1, 21.2, 21.3_

  - [x] 27.2 实现 Reception_Agent 意图抽取与门控编排
    - 实现 `parse_booking_intent`（Cloud_LLM 提示工程/少样本，10s 内，`confidence ∈ [0,1]`，槽位缺失/歧义置 `ambiguous`）
    - 实现 `should_auto_book` 门控与 `handle_booking` 编排：可用且明确→自动预约；满档→回复现状+备选；歧义/低置信/关闭自动预约→请澄清或转 HITL；缺 tenant_id 拒绝
    - 遵循 `ExpertAgent` 协议（`name="reception"`、`run(state)` 返回状态增量）
    - _Requirements: 21.4, 21.5, 21.6, 22.1, 22.5, 24.3_

  - [x] 27.3 接线 Supervisor 新增 reception 意图与预约工具
    - Supervisor 意图分类新增 `reception` 路由到 Reception_Agent（复用既有 Cloud_LLM 分类器）
    - 实现工具层 `schedule_query_tool`（只读）、`appointment_book_tool`（副作用，可自动执行或经 HITL）、`wecom_reply_tool`（扩展既有企业微信推送通道），全部经 RLS 注入 `tenant_id`
    - _Requirements: 21.1, 22.1, 22.5, 24.2_

  - [ ]* 27.4 编写租户隔离与门控属性测试
    - **Property 17: 预约数据租户隔离** — ∀ 预约查询/写入记录 `tenant_id` = 上下文 `tenant_id`
    - **Property 18: 自动预约门控** — ∀ 自动执行预约必满足门控四条件，否则降级/转 HITL
    - **Property 19: 预约意图置信度有界** — ∀ 抽取意图 `confidence ∈ [0,1]`，槽位缺失/歧义时 `ambiguous=True`
    - **Validates: Requirements 21.1, 21.2, 21.3, 22.5, 24.2, 24.3**

  - [ ]* 27.5 编写企业微信预约端到端集成测试
    - 覆盖：可用自动预约（回复确认）/ 满档回复现状+备选 / 歧义转 HITL；并发争抢最后空档仅一笔成功
    - _Requirements: 21.1, 22.1, 23.1, 24.1_

- [x] 28. Checkpoint - 确保企业微信预约模块测试通过
  - 确保所有测试通过，如有疑问请询问用户。

## Notes

- 标记 `*` 的子任务为可选（单元/属性/集成测试），可为快速 MVP 跳过；顶层任务不可标记为可选。
- 每个任务引用了具体需求条款以保证可追溯性。
- 属性测试基于 hypothesis，围绕设计文档"Correctness Properties"的 19 条属性（含企业微信预约模块新增的 Property 14–19）；每条属性均作为独立子任务并标注属性编号与验证的需求条款。
- 企业微信智能客服 + 自动预约排期模块（任务 26–28）复用既有 Supervisor 意图分类、工具层 RLS 注入、事件总线、HITL 与可观测，不改动既有组件；严格沿用范围约束（预约意图理解经 Cloud_LLM 提示工程/少样本，不做微调）。
- 属性测试子任务尽量紧邻其实现任务，以便尽早捕获错误。
- 本计划严格遵守范围约束：Text2SQL 与意图识别经 Cloud_LLM（提示工程/少样本）实现，视觉检测仅经第三方 API，均不含任何模型微调任务。
- Property 1、13 的租户隔离/脱敏在工具层集中实现（任务 7），被后续所有数据访问复用。

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "3.1", "3.3", "4.1", "4.3"] },
    { "id": 3, "tasks": ["2.2", "3.2", "3.4", "4.2", "4.4", "4.5"] },
    { "id": 4, "tasks": ["2.3", "3.5", "4.6", "6.1", "8.1"] },
    { "id": 5, "tasks": ["3.6", "6.2", "7.1", "8.2"] },
    { "id": 6, "tasks": ["7.2", "7.3", "9.1", "10.1", "11.1"] },
    { "id": 7, "tasks": ["7.4", "9.2", "10.2", "11.2"] },
    { "id": 8, "tasks": ["9.3", "11.3", "13.1", "14.1", "15.1", "16.1", "20.1"] },
    { "id": 9, "tasks": ["13.2", "14.2", "15.2", "16.2", "17.1", "18.1", "20.2"] },
    { "id": 10, "tasks": ["15.3", "17.2", "18.2", "21.1"] },
    { "id": 11, "tasks": ["21.2", "21.3", "22.1"] },
    { "id": 12, "tasks": ["22.2", "22.3", "23.1"] },
    { "id": 13, "tasks": ["22.4", "23.2", "24.1"] },
    { "id": 14, "tasks": ["24.2"] },
    { "id": 15, "tasks": ["26.1", "26.2"] },
    { "id": 16, "tasks": ["26.3", "26.4"] },
    { "id": 17, "tasks": ["26.5", "26.6", "27.1", "27.2"] },
    { "id": 18, "tasks": ["27.3"] },
    { "id": 19, "tasks": ["27.4", "27.5"] }
  ]
}
```
