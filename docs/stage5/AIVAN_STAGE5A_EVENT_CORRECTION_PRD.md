# AIVAN Stage 5A 产品需求文档：事件影响分析与不可变纠错

- 文档版本：1.0
- 更新日期：2026-08-05
- 文档状态：Stage 5A 开发/评审基准
- 上位基准：`AIVAN_UNIFIED_PRODUCT_REQUIREMENTS_DOCUMENT_V1_0.md`
- 代码基线：`main@7838c38393f9f42c6c88a218b7f888d6923c0a8c`（PR #56 合并后）
- 对应范围：统一 PRD 的 FR-110，以及 FR-130/FR-140 中与纠错相关的鉴权、租户隔离和审计要求

## 1. 背景与目标

AIVAN 的项目、审批、渠道和操作事件已经进入共享 Core，但错误操作仍缺少统一的“先预览影响、再授权纠正、全程保留证据”闭环。直接修改或删除历史事件会破坏审计连续性，也无法可靠回答“谁在什么授权下纠正了什么、恢复了哪些状态、影响了哪些后续事件”。

Stage 5A 的目标是建立共享 Core 的事件纠错底座：

1. 对单个事件提供租户隔离的影响预览；
2. 只在可证明安全时自动恢复受影响的物化状态；
3. 风险不可自动消解时拒绝自动反转，并允许管理员记录“需要人工补偿”的不可变证据；
4. 原始事件永不物理删除或覆盖；
5. 通过来源关系、前后状态引用、摘要、幂等账本和审计事件形成可核验纠错链。

## 2. 范围

### 2.1 本阶段必须交付

- `GET /api/events/{event_id}/impact`：预览事件、当前物化状态、拟恢复值、后续事件、派生事件、阻断原因和影响摘要。
- `POST /api/events/{event_id}/reverse`：执行安全自动反转，或在显式指定时登记人工补偿要求。
- `execution_events` 增补：`derived_from_event_id`、`payload_digest`、`correction_status`。
- 新增租户级、来源事件级和幂等键级唯一的 `event_reversals` 纠错账本。
- 支持 `case_state` 与 `requirement_json.strategy` 两类已知物化状态的自动恢复。
- 对鉴权失败、跨租户访问、重复请求、状态漂移、后续同字段变更和派生事件提供确定性处理。
- 提供仅增量迁移、摘要回填、单元/接口/迁移回归测试和回滚说明。

### 2.2 明确不属于 Stage 5A

- MyAIVAN Web 工作台、影响预览 UI 和纠错按钮（Stage 5D）。
- MyAIVAN Core API 的完整暴露与 PR #36 拆分迁移（Stage 5B）。
- Email/LINE 自动发送适配和统一渠道注册表（Stage 5C）。
- WeChat/Wangwang Guided Relay 的真机补验和转发卡 UI（后续 Stage 5/6 验收项）。
- 任意事件类型的通用逆向执行器；未明确支持的物化状态必须失败关闭。
- 删除、覆盖或“标记后隐藏”原始审计事件。

## 3. 用户与权限

| 角色 | 查看影响 | 执行反转/登记补偿 | 说明 |
| --- | --- | --- | --- |
| `admin` | 允许 | 允许 | Stage 5A 唯一可执行纠错的业务角色 |
| `auditor` | 允许 | 禁止 | 可审核影响和纠错证据，不得改变业务状态 |
| 其他角色 | 按现有 `VIEW_AUDIT` 能力判定 | 禁止 | 不因前端传入角色字符串获得权限 |

所有请求必须通过现有统一 API Key、可信身份、tenant、trace 和角色处理链。事件查询必须先按 `tenant_id` 限定；跨租户事件统一返回未找到，不泄露其存在性。

## 4. 核心用户流程

### 4.1 影响预览

1. 有审计查看能力的用户请求事件影响。
2. 系统在当前租户内读取来源事件、Case、后续事件、派生事件和既有纠错记录。
3. 系统比较事件 `after` 与当前物化状态，计算能否自动反转。
4. 系统返回恢复目标、阻断项、警告、事件引用及稳定的 `impact_digest`。
5. 此操作不得改变业务状态或写入纠错账本。

### 4.2 安全自动反转

1. 管理员先查看影响，再携带新的 `Idempotency-Key` 和非空 `reason` 请求反转。
2. 系统重新计算影响，避免使用过期前端判断。
3. 仅当没有阻断项时恢复受支持的物化字段。
4. 系统追加 `EVENT_REVERSED` 纠错事件，写入 `event_reversals`，并追加共享审计记录。
5. 来源事件保持原值；纠错事件通过 `derived_from_event_id` 指向来源事件。

### 4.3 人工补偿登记

1. 自动反转因状态漂移、后续同字段修改、派生事件或不支持字段而被阻断。
2. 管理员确认风险后，以 `compensation_only=true` 提交相同纠错请求。
3. 系统不修改 Case 物化状态，仅追加 `EVENT_COMPENSATION_REQUIRED` 及纠错账本。
4. 后续人工处置必须引用该纠错记录；Stage 5A 不伪造“已恢复”结果。

## 5. API 契约

### 5.1 GET `/api/events/{event_id}/impact`

必需请求头沿用统一入口：API Key、租户、可信 actor/role、trace。调用者必须具备 `VIEW_AUDIT`。

成功响应必须包含：

- `source_event`：事件 ID、类型、Case、来源关系、摘要、纠错状态、before/after；
- `affected`：物化字段、当前值、事件 after 预期值、拟恢复值、后续/派生事件数量；
- `downstream_events` 与 `derived_events`：最小事件引用；
- `automatic_reverse_allowed` 与 `compensation_required`；
- `blockers`、`warnings`、`existing_reversal`；
- `impact_digest`：由租户、来源事件、状态和依赖快照规范化计算的 SHA-256。

错误语义：

- `401/403`：身份或能力不足；
- `404`：事件在当前租户不可见或不存在。

### 5.2 POST `/api/events/{event_id}/reverse`

必需请求头：统一鉴权头、`Idempotency-Key`。调用者必须具备 `REVERSE_EVENT`，当前版本仅授予 `admin`。

请求体：

```json
{
  "reason": "纠正原因（必填）",
  "compensation_only": false
}
```

成功响应必须包含纠错状态、是否幂等重放、纠错账本引用、纠错事件引用及执行时重新计算的影响快照。

错误语义：

- `400 IDEMPOTENCY_KEY_REQUIRED`：缺少幂等键；
- `400 REVERSAL_REASON_REQUIRED`：缺少原因；
- `401/403/404`：鉴权、授权或租户范围失败；
- `409 AUTOMATIC_REVERSAL_UNSAFE`：存在自动反转阻断项，响应携带最新影响；
- `409 REVERSAL_CONFLICT`：幂等键已用于其他事件。

## 6. 自动反转判定规则

满足以下全部条件才允许自动反转：

1. 来源事件不是纠错/派生事件，且尚无纠错账本；
2. 当前租户中存在对应 Case；
3. before/after 同时包含受支持的 `case_state` 或 `strategy`；
4. 当前物化值仍等于来源事件记录的 after 值；
5. 来源事件之后不存在修改同一字段的事件；
6. 不存在尚未纠正的派生事件。

任一条件不满足时必须失败关闭。允许返回的主要阻断码包括：

- `event_already_corrected`
- `correction_events_cannot_be_reversed`
- `case_not_found`
- `no_supported_materialized_state`
- `materialized_state_diverged`
- `later_mutation_exists`
- `derived_events_exist`

## 7. 数据与审计要求

### 7.1 `execution_events` 增量字段

- `derived_from_event_id`：纠错或派生事件的来源事件 ID；
- `payload_digest`：事件类型、摘要、payload、before、after 的规范化 SHA-256；
- `correction_status`：空值、`applied` 或 `compensation_required`。

### 7.2 `event_reversals` 账本

至少保存：tenant、Case、来源事件、纠错事件、哈希化幂等键、状态、actor、role、trace、原因、来源摘要、影响摘要、before/after 引用和创建时间。

约束：

- 同租户、同来源事件最多一条纠错决策；
- 同租户、同幂等键最多一条记录；
- 幂等键只保存租户绑定的 SHA-256，不保存调用者明文键；
- 来源事件不因纠错而更新或删除；
- 重放相同请求返回既有结果，不追加重复事件。

## 8. 迁移、兼容与回滚

- 迁移必须默认 preview，只有显式 `--apply` 才写入。
- 迁移只新增表、列和索引，并回填缺失的 `payload_digest`；不删除表、不重写原始业务字段。
- 迁移可重复执行；第二次执行不得产生额外结构或不同摘要。
- 上线前必须备份数据库并记录恢复点。
- 逻辑回滚优先回退应用版本；数据库新增结构和纠错证据不得在生产库中直接删除。
- 如需物理回滚，使用维护窗口前备份恢复，不执行未经批准的破坏性 DDL。

## 9. 验收标准

### 9.1 功能

- 安全的 `case_state` 和 `strategy` 事件可恢复到 before 值；
- 状态漂移、后续同字段修改、派生事件和未知物化字段均阻止自动反转；
- `compensation_only` 不改变物化状态，仅追加补偿证据；
- 来源事件在反转前后逐字段不变；
- 同一幂等键重试只产生一条纠错账本和一条纠错事件。

### 9.2 安全与隔离

- 其他租户无法发现、预览或纠正事件；
- auditor 可查看但无法纠正；非 admin 不获得 `REVERSE_EVENT`；
- 相同幂等键不得跨事件复用；
- API 响应、日志和数据库均不暴露 API Key、密码、私钥或 Token。

### 9.3 数据与迁移

- 历史事件获得稳定、可重复的 payload digest；
- 迁移在已有数据库上 preview、apply、重复 apply 均通过；
- 所有 Stage 5A 测试和仓库完整回归通过；
- PR 描述列出迁移、兼容、安全影响、测试证据及回滚方式，并由 Claude Code 交叉评审。

## 10. 基础设施硬约束

- AIVAN/CTYun 服务器的 `443` 和 `8443` 已由 SSH/MAIL 占用；Stage 5A 不得停止、改绑、复用或修改这两个端口及其现有服务。
- CTYun 访问中国大陆以外 IP 必须经现有 `abcdyi-sin` 新加坡桥接；不得创建直连绕过。
- Stage 5A 不引入新的外部网络依赖，不要求申请 Qwen API Key，也不在仓库或 PR 中保存任何秘密值。
- 本阶段数据库迁移只在取得明确部署授权、完成备份并确认目标环境后执行；PR 合并不等于已部署生产。

## 11. 交付物与阶段分界

Stage 5A 交付物：Core 影响分析服务、纠错服务、两项 API、增量迁移、权限能力、自动化测试、迁移说明和本 PRD。

进入 Stage 5B 的条件：Stage 5A PR 通过 CI 与 Claude Code 交叉评审并获授权合并；主分支回归通过；不存在未解决的 P0 数据完整性或租户隔离问题。

Claude Code/Stage 4 留存项转交后续对应阶段，不作为 Stage 5A 代码完成的虚假声明：

- 当前 main + 当前 OpenClaw/SKILL + 真实手机的 WeChat/Relay 连续五次证据；
- 转发卡 UI 与图片/附件占位行为；
- CTYun 部署证据与新加坡桥接路径；
- 继续证明 AIVAN `443/8443` 未被修改。

## 12. 项目主管审批

- [ ] 批准 Stage 5A 范围和失败关闭策略
- [ ] 批准 admin-only 自动反转权限
- [ ] 批准增量数据库迁移和备份/恢复方案
- [ ] 确认 Stage 4 真机与运维证据转入后续 Stage 5/6
- [ ] 批准 Stage 5A 合并后启动 Stage 5B

主管签名：________________________  日期：________________

审核意见：________________________________________________________________

