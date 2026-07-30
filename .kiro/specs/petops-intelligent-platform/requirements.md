# Requirements Document

## Introduction

本需求文档由已批准的设计文档（`design.md`）反向推导而来，采用 EARS 规范描述 PetOps 智能宠物店运营大脑平台的功能与约束。平台以基于 LangGraph 的多智能体（Supervisor + 专家 Agent）AI 决策中枢为核心，配合统一工具层、事件驱动数据架构、多租户行级安全（RLS）隔离，覆盖客户 LTV 引擎、订阅引擎、健康数据中台、供应链引擎、生态合作网络、社区社交平台、AI 决策中枢共 7 大业务模块。

**本次范围说明（重要）**：
- Text2SQL 与意图分类/路由均通过**云端 LLM（通义千问 / 智谱 GLM）**结合提示工程 / 少样本（few-shot）实现，本次**不包含模型微调**（不涉及 Qwen2.5-7B + LoRA、LLaMA-Factory、vLLM 微调模型）。
- 视觉健康检测**仅**通过**第三方 API（宠智灵 / 百目魔君）**在视觉抽象层之后实现；自研 / 微调 YOLO/ViT 视觉模型不在本次范围（作为未来可选项，不写入本次需求）。
- 其余设计能力（多智能体编排、统一工具层、Human-in-the-loop、多轮有状态 What-if、事件驱动架构、pgvector RAG、特征存储、多租户 RLS、7 大业务模块）均在范围内。

## Glossary

- **PetOps_Platform**：PetOps 智能宠物店运营大脑平台整体系统。
- **Supervisor**：AI 决策中枢的主管 Agent，负责意图识别、任务规划、专家 Agent 路由、结果反思与聚合。
- **Expert_Agent**：专家 Agent 的统称，包含 Analysis_Agent（分析）、Operation_Agent（运营）、Health_Agent（健康）、Supply_Agent（供应链）、Marketing_Agent（营销）。
- **Tool_Layer**：统一工具层，为所有 Agent 提供受控、可审计、租户隔离的数据与模型访问能力。
- **Cloud_LLM**：云端大语言模型（通义千问 / 智谱 GLM），通过提示工程 / 少样本方式驱动 Text2SQL 与意图分类/路由。
- **LTV_Engine**：客户生命周期价值引擎。
- **Subscription_Engine**：订阅引擎。
- **Health_Data_Hub**：健康数据中台。
- **Supply_Chain_Engine**：供应链引擎。
- **Ecosystem_Network**：生态合作网络（含宠物医院转介绍）。
- **Community_Platform**：社区社交平台。
- **RAG_Retriever**：基于 pgvector 的检索增强组件，用于养护问答 / 历史问答 / 相似病例 / 营销内容检索。
- **Feature_Store**：特征存储，为 LTV / churn / demand 模型提供共享特征。
- **Event_Bus**：事件总线（Redis Stream，规模化后演进为 Kafka）。
- **HITL_Checkpoint**：Human-in-the-loop 人工确认检查点。
- **Vision_Provider**：视觉能力抽象接口，本次由第三方 API（宠智灵 / 百目魔君）实现。
- **Observability**：Agent 全链路可观测组件（LangSmith / LangFuse）。
- **RLS_Context**：请求上下文中携带的 `tenant_id` 及 PostgreSQL 行级安全上下文。
- **Life_Stage**：生命阶段，取值为 PUPPY（幼年）、ADULT（成年）、SENIOR（老年）之一。
- **Churn_Score**：客户流失概率，取值范围 [0, 1]。
- **Safety_Stock**：安全库存量。
- **Demand_Forecast**：需求预测结果。
- **WeCom_Gateway**：企业微信入站网关，负责企业微信回调的验签、解密、消息还原，并将客户消息注入 `tenant_id` / `thread_id` 后转发 Supervisor。
- **Reception_Agent**：接待预约 Agent（新增专家 Agent），负责抽取预约意图、调用排期引擎判定可用性、按门控策略自动预约或转 HITL、并生成面向客户的企业微信回复。
- **Scheduling_Engine**：排期引擎（`app/engines/scheduling`），容量/时段模型的权威来源，提供可用性检查、原子预约、备选时段建议与排期查询。
- **Booking_Intent**：由 Cloud_LLM 从对话抽取的预约意图，含服务类型、目标宠物、期望时间、置信度（∈ [0,1]）与歧义标记。
- **Appointment**：预约记录，含 `tenant_id`、`customer_id`、`pet_id`、服务类型、起止时间、资源与状态。
- **Time_Slot**：某服务类型在某时段的容量视图，含容量 `capacity` 与已订数 `booked_count`（满足 `0 ≤ booked_count ≤ capacity`）。
- **Business_Hours**：门店按星期的营业时间（`open_time < close_time`）。
- **Grooming**：洗护 / 洗澡服务（本预约模块的主场景，`ServiceType.GROOMING`）。
- **Auto_Booking_Gating**：自动预约门控策略，规定仅在时段可用、意图明确、置信度达标且租户开启时才自动执行预约，否则降级为满档建议 / 请澄清 / 转 HITL。

## Requirements

### Requirement 1: 意图识别与多智能体编排

**User Story:** 作为店主，我希望通过自然语言提问由系统自动识别意图并路由到合适的专家 Agent，以便无需了解内部结构即可获得专业分析与决策。

#### Acceptance Criteria

1. WHEN 用户提交自然语言请求，THE Supervisor SHALL 在 10 秒内使用 Cloud_LLM 结合提示工程与少样本方式识别请求意图并生成任务规划。
2. WHEN 意图识别完成，THE Supervisor SHALL 将任务路由到 analysis、operation、health、supply、marketing 之一或直接进入聚合阶段。
3. WHILE 存在未完成的规划步骤且累计重规划次数不超过 5 次，THE Supervisor SHALL 在每个专家 Agent 输出后执行反思，判定继续重规划或进入聚合。
4. WHEN 所有规划步骤完成，THE Supervisor SHALL 聚合各专家 Agent 输出并生成最终回答。
5. THE Supervisor SHALL 在处理请求前校验 `state.tenant_id` 为非空值。
6. IF 请求上下文缺少 `tenant_id`，THEN THE Supervisor SHALL 拒绝处理该请求并返回租户上下文缺失的错误提示。
7. IF Cloud_LLM 无法将请求意图识别为上述五类专家 Agent 之一或识别置信度低于设定阈值，THEN THE Supervisor SHALL 拒绝路由该请求并返回要求用户澄清或重述的提示。
8. IF 累计重规划次数达到 5 次上限仍存在未完成的规划步骤，THEN THE Supervisor SHALL 终止重规划并进入聚合阶段，同时在最终回答中标记结果为部分完成。

### Requirement 2: 自然语言数据分析（Text2SQL）

**User Story:** 作为店主，我希望用自然语言查询经营数据，以便快速获得数据洞察而无需手写 SQL。

#### Acceptance Criteria

1. WHEN Analysis_Agent 接收自然语言分析请求，THE Analysis_Agent SHALL 在 30 秒内通过 Cloud_LLM 结合提示工程与少样本方式生成只读 SQL，并经 Tool_Layer 在当前租户 RLS 范围内提交执行。
2. THE Tool_Layer SHALL 对生成的 SQL 执行 SQL 白名单、只读约束与 RLS 三重校验，全部通过后才允许执行。
3. IF 生成的 SQL 无法通过白名单、只读约束或 RLS 中任一校验，THEN THE Tool_Layer SHALL 拒绝执行该 SQL、不对数据库产生任何变更，并返回指明失败原因的澄清提示。
4. WHEN 查询执行成功且结果集非空，THE Analysis_Agent SHALL 返回数据结果集及至少一条基于结果集内容的数据洞察。
5. WHEN 查询执行成功但结果集为空，THE Analysis_Agent SHALL 返回空结果集及无匹配数据的说明。
6. IF 查询执行时间超过 30 秒，THEN THE Tool_Layer SHALL 终止该查询、不对数据库产生任何变更，并返回查询超时错误。
7. WHEN 查询结果集超过 1000 行，THE Tool_Layer SHALL 将结果截断为 1000 行并标记结果已截断。

### Requirement 3: 多轮有状态 What-if 分析

**User Story:** 作为店主，我希望在同一会话中连续追问并进行假设推演，以便基于上一轮结果做进一步决策模拟。

#### Acceptance Criteria

1. WHEN 用户以相同 `thread_id` 发起后续请求，THE Supervisor SHALL 加载该 `thread_id` 持久化的对话状态，并作为本轮请求的上下文提供给后续处理步骤。
2. WHEN 用户提出基于上轮结果的 What-if 假设，THE Operation_Agent SHALL 基于持久化状态执行模拟并返回取值范围为 [0, 1] 的预计召回率与大于等于 0 的预计 GMV。
3. WHEN 一轮请求处理完成，THE Supervisor SHALL 将本轮对话状态以对应的 `thread_id` 持久化，使后续相同 `thread_id` 的请求可加载该状态。
4. IF 请求携带的 `thread_id` 无任何持久化状态，THEN THE Supervisor SHALL 以空会话初始化该 `thread_id` 的对话状态。
5. IF 用户提出 What-if 假设但当前会话不存在可供推演的上轮结果，THEN THE Operation_Agent SHALL 拒绝该模拟请求并返回缺少上轮结果的提示。

### Requirement 4: 副作用动作的人工确认（Human-in-the-loop）

**User Story:** 作为店主，我希望所有会产生副作用的动作在执行前经过我确认，以便防止系统误操作计费、推送或转介绍写入。

#### Acceptance Criteria

1. WHEN 规划包含带副作用的动作（计费、推送、转介绍写入），THE Supervisor SHALL 在 HITL_Checkpoint 中断，向用户展示包含动作类型、目标对象与影响范围的待确认方案，并在获得用户响应前不执行该动作。
2. WHEN 用户在 HITL_Checkpoint 批准待确认动作，THE Tool_Layer SHALL 执行该副作用动作，并在执行成功后向 Event_Bus 发布对应事件。
3. IF 用户在 HITL_Checkpoint 拒绝待确认动作，THEN THE PetOps_Platform SHALL 取消该副作用动作、保持相关数据不被修改，并返回标识该动作未执行的结果。
4. IF HITL_Checkpoint 等待批准超过 300 秒，THEN THE PetOps_Platform SHALL 取消该副作用动作、保持相关数据不被修改，并返回标识该动作因超时未执行的结果。
5. WHEN 副作用动作因拒绝或超时被取消，THE PetOps_Platform SHALL 记录审计日志并向用户发出该动作被取消的通知。

### Requirement 5: 多租户隔离与统一工具层

**User Story:** 作为平台运营方，我希望不同门店的数据在数据库层强隔离，以便杜绝跨租户数据泄露。

#### Acceptance Criteria

1. WHEN Tool_Layer 发起任一数据访问调用，THE Tool_Layer SHALL 将请求上下文的 `tenant_id` 注入 RLS_Context 会话并作为强制过滤条件。
2. WHEN 任一查询返回结果集，THE PetOps_Platform SHALL 确保结果集中每条记录的 `tenant_id` 等于请求上下文的 `tenant_id`。
3. THE PetOps_Platform SHALL 在写入任一携带 `tenant_id` 的实体前经 RLS_Context 校验其 `tenant_id` 为非空值且等于请求上下文的 `tenant_id`。
4. IF 请求上下文缺失或携带空 `tenant_id`，THEN THE Tool_Layer SHALL 拒绝该数据访问调用、不返回任何记录，并报租户上下文缺失错误。
5. IF 查询结果集中存在 `tenant_id` 不等于请求上下文 `tenant_id` 的记录，THEN THE PetOps_Platform SHALL 阻断该结果集返回并报租户隔离违规错误。
6. IF 待写入实体的 `tenant_id` 为空或不等于请求上下文的 `tenant_id`，THEN THE PetOps_Platform SHALL 拒绝该写入、保持数据不变，并报越权错误。

### Requirement 6: 客户 LTV 预测与分层

**User Story:** 作为店主，我希望系统预测客户生命周期价值并对客户分层，以便识别高价值客户并配置运营资源。

#### Acceptance Criteria

1. WHEN 在当前租户范围内调用 LTV 预测且 `horizon_months` 为 1 到 120（含端点）的整数，THE LTV_Engine SHALL 在 10 秒内返回大于等于 0 的 LTV 值。
2. WHEN 对同一客户以更大的 `horizon_months`（取值为 1 到 120 的整数）调用 LTV 预测，THE LTV_Engine SHALL 返回单调不减的 LTV 值。
3. IF `horizon_months` 小于等于 0、大于 120 或非整数，THEN THE LTV_Engine SHALL 拒绝该请求、不返回 LTV 值，并返回参数无效错误。
4. WHEN 店主请求客户分层，THE LTV_Engine SHALL 基于 LTV 与 Churn_Score 将每个客户分配到 高价值、成长、流失风险 三个分层中的恰好一个。
5. WHEN 对两名客户进行分层且其一 LTV 更高且 Churn_Score 更低，THE LTV_Engine SHALL 使该客户的分层不低于另一名客户的分层。
6. IF 客户不存在于当前租户或其历史交易数据不足，THEN THE LTV_Engine SHALL 拒绝该请求、不返回 LTV 值，并返回客户不存在或数据不足错误。

### Requirement 7: 客户流失预测

**User Story:** 作为店主，我希望系统预测客户流失概率，以便及时对高流失风险客户开展召回。

#### Acceptance Criteria

1. WHEN 提供 RFM（近度、频度、金额）与行为特征均为非空的特征向量，THE Operation_Agent SHALL 在 10 秒内返回取值范围为 [0, 1]（含端点 0 与 1）的 Churn_Score。
2. WHEN 对除活跃度相关特征外其余特征均相同的两名客户计算流失分数，THE Operation_Agent SHALL 使活跃度更高客户的 Churn_Score 不高于活跃度更低客户的 Churn_Score（活跃度越高，Churn_Score 单调不增）。
3. IF 特征向量为空，THEN THE Operation_Agent SHALL 拒绝该请求、不返回 Churn_Score，并返回指明特征缺失的错误。
4. IF 特征向量缺少 RFM（近度、频度、金额）必需特征中的任一项，或存在取值超出其有效范围的特征，THEN THE Operation_Agent SHALL 拒绝该请求、不返回 Churn_Score，并返回指明特征无效或缺失的错误。

### Requirement 8: 订阅引擎与计费

**User Story:** 作为店主，我希望管理订阅套餐并按周期计费，以便实现稳定的订阅收入。

#### Acceptance Criteria

1. WHEN 店主创建订阅套餐且套餐规格通过校验（计费周期为 monthly、quarterly、yearly 之一，金额在 0.01 到 999,999,999.99 元之间），THE Subscription_Engine SHALL 在 5 秒内保存套餐规格并返回套餐标识。
2. IF 套餐规格校验失败（计费周期非法或金额越界），THEN THE Subscription_Engine SHALL 拒绝创建、不保存数据，并返回指明无效字段的错误。
3. WHEN 运行计费周期，THE Subscription_Engine SHALL 对状态为 active 的订阅生成计费，并返回包含成功笔数、失败笔数与失败原因的计费报告。
4. IF 单笔订阅计费失败，THEN THE Subscription_Engine SHALL 跳过该笔、保持其扣费状态不变，并记录失败原因。
5. WHERE 计费动作会产生实际扣费，THE Subscription_Engine SHALL 经 HITL_Checkpoint 确认后才执行扣费，且在批准前不扣费、不修改账务数据。
6. WHEN 单笔扣费成功完成，THE Subscription_Engine SHALL 向 Event_Bus 发布 `subscription_billed` 事件。

### Requirement 9: 健康数据中台与事件驱动预警

**User Story:** 作为宠主，我希望上报的宠物健康数据被持续监测并在异常时预警，以便及时干预宠物健康问题。

#### Acceptance Criteria

1. WHEN 智能设备或 APP 上报体重、活动或饮食数据且数据通过校验，THE Health_Data_Hub SHALL 在 5 秒内将数据写入时序表并向 Event_Bus 发布 `health_data_ingested` 事件。
2. IF 上报的健康数据缺少 `tenant_id` 或数值超出有效范围（如体重小于等于 0），THEN THE Health_Data_Hub SHALL 拒绝写入、保持时序表不变、不发布 `health_data_ingested` 事件，并返回指明校验失败原因的错误提示。
3. WHEN Event_Bus 接收到 `health_data_ingested` 事件，THE Health_Agent SHALL 在 30 秒内基于该宠物最近 30 天的时序数据执行异常趋势检测。
4. IF 检测到健康异常趋势（如体重在 7 天内下降超过 10%），THEN THE Health_Agent SHALL 向 Event_Bus 发布携带级别为 低、中、高 之一的 `health_alert` 事件并生成对应的预警任务。
5. WHEN 生成级别为高的 `health_alert` 事件，THE Health_Agent SHALL 通过 Ecosystem_Network 生成转介绍合作宠物医院的建议。

### Requirement 10: 生命阶段判定

**User Story:** 作为系统，我希望根据物种、品种、月龄判定宠物生命阶段，以便为健康与推荐提供依据。

#### Acceptance Criteria

1. WHEN 提供包含物种、品种且 `age_months` 取值在 [0, 360]（含端点，单位：月）的宠物信息，THE PetOps_Platform SHALL 返回 PUPPY、ADULT、SENIOR 之一的 Life_Stage。
2. THE PetOps_Platform SHALL 使成年标准体重较大的犬型（大型犬）的 SENIOR 起始 `age_months` 阈值不大于成年标准体重较小的犬型（小型犬）的 SENIOR 起始 `age_months` 阈值。
3. IF `age_months` 小于 0 或大于 360，THEN THE PetOps_Platform SHALL 拒绝该请求、不返回任何 Life_Stage，并返回参数无效错误。
4. WHEN 对同一物种与品种以递增的 `age_months` 连续判定生命阶段，THE PetOps_Platform SHALL 返回按 PUPPY→ADULT→SENIOR 顺序单调不回退的 Life_Stage。
5. IF 请求缺少物种或品种，或提供的物种为系统不支持的类型，THEN THE PetOps_Platform SHALL 拒绝该请求、不返回任何 Life_Stage，并返回参数无效错误。
6. WHERE 提供的品种为系统未收录品种但物种受支持，THE PetOps_Platform SHALL 回退到该物种的默认生命阶段阈值判定并返回 Life_Stage。

### Requirement 11: 需求预测

**User Story:** 作为店主，我希望系统基于历史销量预测未来需求，以便支撑补货决策。

#### Acceptance Criteria

1. WHEN 调用需求预测且 `horizon_days` 为大于 0 且小于等于 365 的整数，THE Supply_Chain_Engine SHALL 在 30 秒内返回 `predicted_demand` 大于等于 0 且 `confidence` 取值范围为 [0, 1] 的 Demand_Forecast。
2. IF SKU 可用历史销量数据少于 30 天，THEN THE Supply_Chain_Engine SHALL 回退到移动平均法生成 `predicted_demand` 大于等于 0 且 `confidence` 取值范围为 [0, 1] 的 Demand_Forecast，并将该结果标记为回退（降级）结果。
3. IF `horizon_days` 小于等于 0、大于 365 或非整数，THEN THE Supply_Chain_Engine SHALL 拒绝该请求、不返回 Demand_Forecast，并返回参数无效错误。
4. IF SKU 无任何历史销量数据，THEN THE Supply_Chain_Engine SHALL 拒绝该请求、不返回 Demand_Forecast，并返回历史数据缺失错误。

### Requirement 12: 安全库存与再订货点

**User Story:** 作为店主，我希望系统按服务水平计算安全库存与再订货点，以便在避免缺货的同时控制库存成本。

#### Acceptance Criteria

1. WHEN 调用安全库存计算且 `service_level` 取值在 (0, 1)、`lead_time_days` 取值在 (0, 365]、`avg_daily_demand` 大于等于 0，THE Supply_Chain_Engine SHALL 返回大于等于 0 的 Safety_Stock。
2. WHEN 对同一 SKU 在 `lead_time_days` 与 `avg_daily_demand` 保持不变、`service_level` 取值在 (0, 1) 且更高时计算安全库存，THE Supply_Chain_Engine SHALL 返回不减的 Safety_Stock。
3. WHEN 计算安全库存完成，THE Supply_Chain_Engine SHALL 基于平均日需求、提前期与安全库存返回大于等于 0 且大于等于 Safety_Stock 的再订货点。
4. IF `service_level` 不在 (0, 1)、`lead_time_days` 不在 (0, 365] 或 `avg_daily_demand` 小于 0，THEN THE Supply_Chain_Engine SHALL 拒绝该请求、不返回 Safety_Stock 与再订货点，并返回参数无效错误。

### Requirement 13: 推荐规则引擎

**User Story:** 作为店主，我希望系统结合生命阶段、健康、流失与库存生成可解释的商品推荐，以便向客户提供精准且可售的推荐。

#### Acceptance Criteria

1. WHEN 生成推荐结果，THE PetOps_Platform SHALL 在 5 秒内返回按 `score` 降序排列、`score` 取值范围为 [0, 1]、最多 20 条的推荐列表，且 `score` 并列时按 SKU 标识升序稳定排序。
2. WHEN 生成推荐列表，THE PetOps_Platform SHALL 排除可售库存小于等于 0 的缺货 SKU。
3. WHEN 生成每条推荐，THE PetOps_Platform SHALL 为该推荐附带基于生命阶段、健康、流失分数与库存可售性的可解释理由 `reason`。
4. IF 客户的 `tenant_id` 不等于当前请求上下文的 `tenant_id`，THEN THE PetOps_Platform SHALL 拒绝该推荐请求、不返回任何推荐，并返回越权错误。
5. WHEN 不存在满足条件的可推荐候选，THE PetOps_Platform SHALL 返回空推荐列表。

### Requirement 14: 生态合作网络与转介绍

**User Story:** 作为店主，我希望在健康预警时向合作宠物医院发起转介绍，以便为客户提供延伸服务并形成生态协同。

#### Acceptance Criteria

1. WHEN 收到级别为高的 `health_alert` 事件而需发起转介绍，THE Ecosystem_Network SHALL 在 5 秒内构造包含目标合作宠物医院、客户标识、宠物标识与转介绍原因的转介绍动作并提交至 HITL_Checkpoint 待确认，且在确认前不执行任何转介绍写入。
2. WHEN 转介绍动作获批准，THE Ecosystem_Network SHALL 执行转介绍写入。
3. WHEN 转介绍写入成功完成，THE Ecosystem_Network SHALL 向 Event_Bus 发布对应的转介绍事件。
4. IF 转介绍涉及的客户或宠物的 `tenant_id` 不等于请求上下文的 `tenant_id`，THEN THE Ecosystem_Network SHALL 拒绝该转介绍、不执行写入，并返回越权错误。
5. IF 不存在可匹配的合作宠物医院，THEN THE Ecosystem_Network SHALL 拒绝发起该转介绍、不提交至 HITL_Checkpoint，并返回无可用合作方的提示。

### Requirement 15: 社区社交平台与内容生成

**User Story:** 作为运营人员，我希望系统辅助生成营销与社区内容，以便提升内容运营效率。

#### Acceptance Criteria

1. WHEN 运营人员在当前租户范围内请求生成营销或社区内容，THE Marketing_Agent SHALL 在 30 秒内通过 Cloud_LLM 结合提示工程与 RAG_Retriever 检索到的知识片段生成并返回内容结果。
2. WHERE 内容生成需要参考知识片段，THE Marketing_Agent SHALL 通过 RAG_Retriever 在当前租户及平台级共享知识范围内检索相关内容片段作为生成依据。
3. IF 请求上下文缺少 `tenant_id`，THEN THE Marketing_Agent SHALL 拒绝该内容生成请求、不生成任何内容，并返回租户上下文缺失的错误提示。
4. IF Cloud_LLM 调用超时或不可用，THEN THE Marketing_Agent SHALL 不返回生成内容，并返回指明内容生成失败原因的错误提示。
5. IF 内容生成需要参考知识片段但 RAG_Retriever 未检索到任何相关片段，THEN THE Marketing_Agent SHALL 不基于未检索到的片段生成内容，并返回缺少可参考知识片段的提示。

### Requirement 16: 养护问答 RAG 检索

**User Story:** 作为宠主，我希望获得基于知识库的养护问答，以便得到可靠且可更新的养护建议。

#### Acceptance Criteria

1. WHEN 用户发起养护问答请求且请求上下文携带非空 `tenant_id`，THE RAG_Retriever SHALL 在 5 秒内基于 pgvector 在当前租户私有知识与平台级共享知识范围内，返回按相似度得分降序排列、相似度得分不低于设定阈值且最多 5 条的知识片段。
2. WHEN 检索返回至少一条满足相似度阈值的知识片段，THE PetOps_Platform SHALL 在 30 秒内结合 Cloud_LLM 与检索到的知识片段生成养护问答回答，并在回答中标注所引用的知识片段来源。
3. WHERE 知识片段的 `tenant_id` 为空，THE RAG_Retriever SHALL 将该片段视为平台级共享知识，可被所有租户检索。
4. IF 养护问答请求上下文缺失或携带空 `tenant_id`，THEN THE RAG_Retriever SHALL 拒绝该检索请求、不返回任何知识片段，并返回租户上下文缺失错误。
5. IF 检索未返回任何满足相似度阈值的知识片段，THEN THE PetOps_Platform SHALL 不调用 Cloud_LLM 生成回答，并返回知识库中无匹配养护知识的提示。

### Requirement 17: 视觉健康检测（第三方 API）

**User Story:** 作为宠主，我希望上传宠物照片获得健康检测结果，以便初步了解宠物健康状况。

#### Acceptance Criteria

1. WHEN 用户提交格式为 JPEG 或 PNG 且大小不超过 10 MB 的宠物图像进行健康检测，THE Vision_Provider SHALL 在 30 秒内通过第三方 API（宠智灵 / 百目魔君）返回包含至少一个检测项及取值范围 [0, 1] 置信度的视觉检测结果。
2. THE PetOps_Platform SHALL 通过 Vision_Provider 抽象接口访问视觉检测能力，使业务代码不感知底层第三方来源。
3. IF 提交的图像格式非 JPEG/PNG、大小超过 10 MB 或图像缺失，THEN THE PetOps_Platform SHALL 拒绝该请求、不调用第三方 API，并返回图像无效错误。
4. IF 第三方视觉 API 不可用或响应超过 30 秒，THEN THE Vision_Provider SHALL 切换备用 provider 或以最多 3 次重试排队重发。
5. IF 重试耗尽后仍无法获得检测结果，THEN THE PetOps_Platform SHALL 将检测结果标记为待人工复核并保留原始图像。

### Requirement 18: 事件驱动架构与可追溯

**User Story:** 作为平台运营方，我希望系统以事件驱动方式解耦并对 Agent 决策全链路留痕，以便实现异步处理、审计与合规。

#### Acceptance Criteria

1. WHEN 业务后端或健康中台产生领域事件，THE Event_Bus SHALL 在 2 秒内将该事件分发给 Agent 触发器、特征更新消费者、通知推送消费者与审计日志消费者，且每个消费者至少接收该事件一次。
2. WHEN Supervisor 或任一 Expert_Agent 产生决策，THE Observability SHALL 为该决策链留存包含关联 trace ID、请求输入、参与决策的各 Agent 标识、各决策节点输出与各节点起止时间戳的追溯记录。
3. THE Observability SHALL 将每条决策追溯记录至少保留 180 天。
4. IF 事件消费失败，THEN THE Event_Bus SHALL 以指数退避策略对该事件最多重试 3 次。
5. IF 事件在重试 3 次后仍消费失败，THEN THE Event_Bus SHALL 将该事件转入死信队列（DLQ），保留原始事件内容，并在 60 秒内向运营方触发告警。

### Requirement 19: 特征存储共享

**User Story:** 作为系统，我希望 LTV、churn、demand 模型共享同一特征存储，以便避免重复计算与训练-服务偏斜。

#### Acceptance Criteria

1. THE Feature_Store SHALL 为 LTV、churn、demand 模型提供统一的特征读写接口。
2. WHEN 请求在线特征，THE Feature_Store SHALL 通过 Redis 支撑的在线通道在 100 毫秒内返回特征。
3. WHEN 从在线通道与离线通道读取同一实体的同一特征，THE Feature_Store SHALL 返回一致的特征值。
4. IF Feature_Store 缺少对应特征，THEN THE PetOps_Platform SHALL 使用默认值并打标、不中断当前请求，同时触发离线特征回填。
5. IF 在线特征通道（Redis）不可用，THEN THE Feature_Store SHALL 降级回退到离线通道读取特征。

### Requirement 20: 错误处理与降级

**User Story:** 作为平台运营方，我希望系统在外部依赖异常时优雅降级，以便保障核心可用性。

#### Acceptance Criteria

1. IF Cloud_LLM 调用超过 10 秒超时或被限流，THEN THE PetOps_Platform SHALL 以初始 1 秒、每次翻倍、上限 8 秒的指数退避最多重试 3 次，并在重试耗尽后降级到受限模板查询。
2. IF Text2SQL 生成的 SQL 越权或非法，THEN THE PetOps_Platform SHALL 拒绝执行该 SQL、不对数据库产生任何变更，并回退到受限模板查询。
3. WHILE 敏感数据（手机号、身份证号、银行卡号）被展示，THE PetOps_Platform SHALL 对其中间部分字符进行掩码后再展示。
4. IF Cloud_LLM 在 60 秒窗口内连续失败达到 5 次，THEN THE PetOps_Platform SHALL 触发熔断并在其后 30 秒内将后续请求直接降级到受限模板查询。
5. IF 受限模板查询无法匹配用户请求，THEN THE PetOps_Platform SHALL 返回请用户重述请求的提示。
6. WHILE 敏感数据被存储，THE PetOps_Platform SHALL 以脱敏形式存储该敏感字段。

### Requirement 21: 企业微信智能客服接入与预约意图理解

**User Story:** 作为宠主，我希望通过企业微信用自然语言表达洗护预约意图（如"想约周六下午给狗狗洗澡"），以便无需操作小程序即可发起预约。

#### Acceptance Criteria

1. WHEN 企业微信回调携带客户入站消息且验签与解密通过，THE WeCom_Gateway SHALL 还原客户消息、将其映射到的门店 `tenant_id` 与会话 `thread_id` 注入请求上下文，并转发至 Supervisor。
2. IF 企业微信回调验签或解密失败，THEN THE WeCom_Gateway SHALL 拒绝处理该回调、不将其转发至决策中枢，并记录该事件。
3. IF 入站消息的 `msg_id` 与已处理消息重复，THEN THE WeCom_Gateway SHALL 幂等去重、不重复触发预约处理，并返回首次处理的结果。
4. WHEN Supervisor 将预约相关消息路由至 Reception_Agent，THE Reception_Agent SHALL 在 10 秒内经 Cloud_LLM 结合提示工程与少样本方式抽取 Booking_Intent（服务类型、目标宠物、期望时间），且其 `confidence` 取值范围为 [0, 1]。
5. IF 抽取出的服务类型、目标宠物或期望时间中任一缺失或存在歧义（如同一客户名下多只宠物无法消解、时间表述模糊），THEN THE Reception_Agent SHALL 将该 Booking_Intent 标记为 `ambiguous = True`。
6. IF 入站请求上下文缺失或携带空 `tenant_id`，THEN THE Reception_Agent SHALL 拒绝处理该预约请求、不返回任何预约结果，并返回租户上下文缺失错误。

### Requirement 22: 自动预约排期与容量控制

**User Story:** 作为宠主，我希望在目标时段有空档时系统直接为我自动预约洗护，以便快速确定到店时间。

#### Acceptance Criteria

1. WHEN 目标时段有剩余容量、Booking_Intent 无歧义、`confidence` 不低于设定阈值且该租户已开启自动预约，THE Scheduling_Engine SHALL 在同一事务内原子写入一条状态为 CONFIRMED 的 Appointment，并经企业微信回复预约确认。
2. THE Scheduling_Engine SHALL 保证对任一（门店、服务类型、重叠时段）处于 PENDING 或 CONFIRMED 状态的预约数不超过该时段容量 `capacity`（绝不超容量）。
3. WHEN 一条预约写入成功完成，THE Scheduling_Engine SHALL 向 Event_Bus 发布 `appointment_booked` 事件。
4. IF 目标时段不完全落在门店对应营业时间内，THEN THE Scheduling_Engine SHALL 拒绝该预约、不产生任何写入，并返回时段超出营业时间的错误。
5. WHERE Booking_Intent 存在歧义、`confidence` 低于阈值或该租户关闭自动预约，THE Reception_Agent SHALL 不自动写入预约，而是请客户澄清或将该预约动作提交至 HITL_Checkpoint 待确认。
6. IF 待预约的 Appointment 的 `start_at` 不早于 `end_at`，THEN THE Scheduling_Engine SHALL 拒绝该预约、不产生任何写入，并返回时间区间无效错误。

### Requirement 23: 满档备选时段建议

**User Story:** 作为宠主，当我想约的时段已满时，我希望系统告诉我当前排期情况并推荐其他可约时间，以便我改约。

#### Acceptance Criteria

1. WHEN 目标时段的剩余容量为 0（满档），THE Reception_Agent SHALL 经企业微信回复该服务当日的排期占用现状，并给出至多 N 个（N 为配置的建议数量）备选时段建议。
2. THE Scheduling_Engine SHALL 保证每个返回的备选时段剩余容量大于 0 且完全落在营业时间内，并按与期望时间的接近度升序排列（同一天优先，其次后续日期）。
3. IF 在设定搜索范围（默认 7 天）内不存在任何剩余容量大于 0 的时段，THEN THE Scheduling_Engine SHALL 返回空的备选列表，且 THE Reception_Agent SHALL 回复暂无可约时段的提示。
4. WHEN 目标时段满档，THE Scheduling_Engine SHALL 向 Event_Bus 发布 `appointment_rejected_full` 事件。

### Requirement 24: 预约并发安全与租户隔离

**User Story:** 作为平台运营方，我希望预约写入在并发下不超卖且严格租户隔离，以便杜绝重复占位与跨租户数据泄露。

#### Acceptance Criteria

1. WHEN 多个预约请求并发争抢同一时段的最后一个空档，THE Scheduling_Engine SHALL 以行级锁串行化"检查—写入"，仅允许其中一笔成功、其余按满档处理，且失败请求不产生任何部分写入。
2. WHEN 任一预约查询返回结果集或任一预约写入落库，THE PetOps_Platform SHALL 确保其每条记录的 `tenant_id` 等于请求上下文的 `tenant_id`。
3. IF 预约涉及的客户或宠物的 `tenant_id` 不等于请求上下文的 `tenant_id`，THEN THE Scheduling_Engine SHALL 拒绝该预约、不执行写入，并返回越权错误。
4. WHERE 预约动作以自动方式（无人工确认）执行，THE PetOps_Platform SHALL 仅在满足自动预约门控（时段可用、意图无歧义、置信度达标、租户已开启自动预约）时执行，否则转 HITL_Checkpoint。


### Requirement 25: 管理后台顶栏与多标签工作区

**User Story:** 作为门店员工，我希望后台顶栏具有清晰的操作语义，并以浏览器式标签页保留已访问业务页面，以便在多个经营任务之间快速切换而不会迷失上下文。

#### Acceptance Criteria

1. THE 管理后台 SHALL 在顶栏完整显示侧栏收起/展开、全局搜索、大屏入口与当前登录用户菜单的图标和可访问名称，且不得因缺少图标导入而显示空白控件。
2. THE 管理后台 SHALL 将顶栏的剩余空间用于明确的工作区信息与操作区，而不是呈现无意义的大面积空白；全局搜索在常规桌面宽度下宽度不得超过 360px，窄屏时可收缩而不挤出用户操作区。
3. WHEN 已认证用户访问除登录页和大屏页以外的业务路由，THE 管理后台 SHALL 为该路由注册一个标签页，并以路由 `meta.title` 显示中文业务标题。
4. THE 管理后台 SHALL 始终保留“仪表盘”标签且该标签不可关闭；同一 `fullPath` 不得出现重复标签。
5. WHEN 用户单击标签页，THE 管理后台 SHALL 跳转至该标签对应的完整路由并将其标记为激活状态。
6. WHEN 用户关闭非仪表盘标签，THE 管理后台 SHALL 移除该标签；IF 被关闭的是当前激活标签，THEN THE 管理后台 SHALL 跳转至其右侧相邻标签，若不存在则跳转左侧相邻标签，若均不存在则跳转仪表盘。
7. WHEN 用户刷新已认证后台页面，THE 管理后台 SHALL 从会话存储恢复仍对应业务路由的标签列表与当前标签；无效、重复、登录页和大屏页标签 SHALL 被丢弃。
8. THE 标签栏 SHALL 在标签超出可视区域时支持水平滚动，当前标签须具备清晰的强调态，非当前标签须提供独立关闭按钮且关闭操作不得触发标签切换。


### Requirement 26: 公众号宠主会话、未建档建档与服务边界

**User Story:** 作为通过公众号联系门店的宠主，我希望系统先识别我是新客还是已建档客户，并只围绕门店可提供的宠物服务继续对话，以便能自然地完成资料补充、预约或咨询，而不会看到门店内部运营功能或误导性的处理状态。

#### Acceptance Criteria

1. WHEN 公众号回调接收到宠主文本消息，THE PetOps_Platform SHALL 将会话标记为 `channel=wechat_public` 与 `customer_facing=True`，并保留用于会话续接的 `openid`、`tenant_id` 与 `thread_id`。
2. WHEN `channel=wechat_public`，THE PetOps_Platform SHALL 仅向宠主开放门店服务范围内的会话能力：洗护/美容/寄养等到店服务预约、预约信息补充或调整、宠物养护与健康咨询、以及人工服务引导；不得将数据分析、客户运营、库存供应链、营销内容或其他内部经营能力展示为宠主可选操作。
3. WHEN 预约意图提示模板包含 JSON 示例或其他花括号字面量，THE PetOps_Platform SHALL 安全渲染该模板，使服务类型、宠物、时间等示例字段不会被字符串插值机制解释为变量；模板渲染不得因该类字面量抛出未处理异常。
4. WHEN 公众号 `openid` 在当前租户无法匹配客户档案，THE PetOps_Platform SHALL 在任何通用意图识别或内部能力路由之前进入宠主建档流程，并在该流程中保留当前消息及已提取的服务诉求。
5. WHEN 未建档宠主进入建档流程，THE PetOps_Platform SHALL 优先收集并保存宠主姓名与宠物名称；在姓名或宠物名称、手机号、物种、品种任一信息尚未齐全时，THE PetOps_Platform SHALL 将档案标记为 `onboarding_pending`，而不得将缺失的物种或品种伪造为事实性 `unknown` 值。
6. WHILE 档案处于 `onboarding_pending`，THE PetOps_Platform SHALL 在后续自然对话中逐步收集手机号、物种和品种；宠主表达预约或咨询诉求时，THE PetOps_Platform SHALL 保留该诉求并继续推进必要的服务信息收集，而不得因资料尚未完整而要求宠主重新发起诉求。
7. WHEN 公众号宠主的服务诉求不完整、无法识别或需进一步确认，THE PetOps_Platform SHALL 使用仅涉及宠物门店服务的澄清话术，引导宠主补充服务类型、宠物、期望时间或咨询问题；该话术不得提及内部经营功能。
8. IF 公众号消息处理发生未预期异常，THEN THE PetOps_Platform SHALL 记录包含关联标识与异常详情的服务端错误日志，并向宠主返回可继续对话的服务引导；该回复不得宣称消息已处理、已受理或将尽快处理，也不得泄露异常堆栈、密钥或内部实现细节。
