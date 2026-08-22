# AIVAN Stage 6 产品需求文档：候选版本冻结、连续验收与发布交接

- 文档版本：1.0
- 更新日期：2026-08-06
- 文档状态：Stage 6 执行基准；生产发布仍须项目主管单独批准
- 上位基准：`AIVAN_UNIFIED_PRODUCT_REQUIREMENTS_DOCUMENT_V1_0.md`
- 当前代码基线：`main@e576e8c7d209c1a6c31dc7712e42a8f5d83c6ca7`（PR #57 合并后）
- 覆盖要求：统一 PRD §13、§17，FR-001–FR-150 的发布验收，以及 Stage 1–5 的剩余运行证据

## 1. 背景与目标

Stage 1–5A 已把统一入口、身份与租户、多角色共享模型、AIVAN-OpenClaw 制品、Guided Relay 和不可变事件纠错合入 `main`。Stage 6 不再增加新的业务状态机，其目标是冻结同一个候选版本，在可审计条件下证明产品闭环可重复、安全、可恢复，并形成可由项目主管签字的发布与交接证据。

Stage 6 必须坚持“代码存在不等于产品交付”。单元测试、历史真机记录、README 声明、未合并 PR 或外部系统返回 HTTP 200，均不能单独替代当前候选版本的端到端验收。

## 2. 当前基线与未满足依赖

### 2.1 已合并基线

- Stage 1：统一入口、鉴权、租户、trace、幂等与结构化错误。
- Stage 2：业务角色、会话角色、执行模式、Case/Conversation/Participant/Approval/Audit 共享模型。
- Stage 3：AIVAN-OpenClaw Plugin + SKILL 正式制品及六项工具契约。
- Stage 4：Email/LINE `auto_send`、WeChat/Wangwang `guided_relay`、WhatsApp `unsupported` 的能力矩阵，以及 Relay outbox/confirm/inbound Core 路径。
- Stage 5A：事件影响预览、admin-only reversal、不可变纠错账本和增量迁移。
- PR #57 合并时 CI 5/5，通过 Python 3.11/3.12/3.13、TypeScript 和 Dependency Review；本地回归为 751 passed、2 skipped。

### 2.2 Stage 6 开始时仍未交付

以下项目是发布阻断项，不得因启动 Stage 6 而被视为完成：

1. Stage 5B：MyAIVAN 必须复用共享 Core，不得引入 PR #36 的独立 `web_*` Case、草稿或审计状态机。
2. Stage 5C：Email/LINE 的实际受控 Adapter、真实回执、失败分类和受控重试尚需候选版本证据。
3. Stage 5D：MyAIVAN 的角色、审批人、渠道模式、依赖错误、Relay 卡、影响预览、纠错动作、回执和审计时间线 UI 尚需交付。
4. 当前 main + 当前 OpenClaw/SKILL + 真实手机的 WeChat/Relay 连续五次闭环证据尚未形成。
5. 转发卡 UI 与图片/附件占位行为尚未形成当前版本证据。
6. Claude Code 指出 Stage 5A 的 7 个失败关闭阻断码中，仅 `later_mutation_exists` 有专门断言；其余 6 项必须在候选版本冻结前补测。

## 3. Stage 6 分段

### Stage 6A：发布门禁与自动验收底座（可立即执行）

- 补齐 Stage 5A 六个阻断码的专门自动化断言：
  - `event_already_corrected`
  - `correction_events_cannot_be_reversed`
  - `case_not_found`
  - `no_supported_materialized_state`
  - `materialized_state_diverged`
  - `derived_events_exist`
- 建立需求 → 代码 → 测试 → 运行证据追踪矩阵。
- 建立五连测执行器；任一次失败后整组归零，修复后从第 1 次重新计数。
- 记录候选提交、依赖锁摘要、配置档案、测试环境和证据摘要；不得记录秘密值。
- 将 Stage 5B–5D 和真实外部环境标记为显式未满足门禁，而不是自动跳过。

### Stage 6B：候选版本冻结

仅在 Stage 5B–5D 全部通过独立 PR、CI 和交叉评审后执行：

- 冻结唯一候选 commit、Python/Node/OpenClaw/Plugin/SKILL 版本及 `uv.lock`/前端 lockfile；
- 冻结数据库迁移顺序、配置变量名称、测试数据和外部依赖版本；
- 生成候选版本清单和构建来源证明；
- 冻结后任何代码、依赖或配置变更均产生新候选版本，原五连测证据失效。

### Stage 6C：CTYun 受控部署与数据恢复准备

- 取得项目主管明确部署授权并登记维护窗口；
- 部署前完成数据库和必要对象存储备份，记录校验值、恢复位置和保留策略；
- preview 并按顺序执行已批准的增量迁移，重复 preview 验证 `already_exists`；
- 使用现有进程/容器管理方式部署，不改变未授权基础设施；
- 执行健康、版本、数据库和依赖检查；失败立即停止推进并按批准方案回滚；
- 至少完成一次隔离环境恢复演练，证明备份可读、可校验、可恢复。

### Stage 6D：连续五次产品验收

在同一候选版本、同一配置档案和同一外部依赖版本上，对每个 P0 场景连续运行五次：

1. MyAIVAN 创建 Case、粘贴多语言 RFQ、保留原文和字段来源；
2. 缺失关键字段时门禁停止下游并提出具体问题；
3. 完整 RFQ 调用 giraffe-db/GPM/GLTG，不伪造依赖结果；
4. 多重角色转换、非法权限、跨租户和错误线程均失败关闭；
5. 草稿审批、拒绝、修订和发送前状态一致；
6. Email 与 LINE 批准后自动发送并保存真实回执；
7. WeChat 与 Wangwang 只进入 Guided Relay，人发送、人确认、保留回执；
8. 当前 OpenClaw Plugin/SKILL 的六项工具实际枚举并调用；
9. 事件影响预览、自动反转、补偿登记和更正草稿闭环；
10. Token Guard 的预算、上下文、并发、排队、超时、EOF 和截断保护；
11. MyAIVAN Markdown 导出包含会话、草稿、状态、回执和审计时间线；
12. 外部依赖失败、服务重启和发送失败可见且可恢复。

任意场景任意一次失败，必须记录根因、修复或外部状态变化，并将该场景的连续计数归零。不得删除失败证据。

### Stage 6E：安全、容量、监控与交接

- 执行鉴权、RBAC、跨租户对象引用、幂等、秘密扫描、依赖审查和附件授权测试；
- 验证私域基线无未经批准的外部 LLM/VLM 调用；
- 在当前 AIVAN Qwen/Ollama 配置上记录吞吐、首 token、总延迟、输出 token、队列等待、超时和内存峰值；
- 验证日志和指标可关联 tenant（脱敏）、Case、trace、event、draft、approval 和 receipt；
- 配置依赖失败、Token Guard、发送失败、Relay 积压、数据库和磁盘/对象存储告警；
- 形成运行手册、回滚/恢复 SOP、值班入口、已知限制和责任人清单；
- 由产品、技术、运维和项目主管共同签字。

## 4. 证据模型

每次自动或人工验收记录至少包含：

```text
evidence_id, stage, scenario_id, requirement_ids
candidate_commit, dependency_lock_digests, environment_profile
run_sequence, started_at, completed_at, result
tenant_test_alias, case_id, source_trace_id
artifact_references, receipt_references, log_references
failure_code, root_cause_reference, reviewer, approved_at
```

要求：

- `tenant_test_alias` 只能使用脱敏测试别名；
- artifact/receipt/log 只保存授权引用和摘要，不复制密码、Token、私钥或生产敏感正文；
- 自动化证据输出必须采用追加方式；
- 手工截图必须遮蔽联系人、账号、密钥、主机秘密和非必要业务内容；
- 证据必须能回溯到唯一候选 commit，不能把旧版本记录继承为新版本通过。

## 5. 五连测执行规则

- 默认要求 `required_consecutive_runs=5`，不得通过参数降低正式验收门槛；
- 每次运行使用独立幂等键和测试 Case，避免把重放误计为新成功；
- 每次运行验证业务状态、事件数量、审计、回执和外部可观察结果，而不仅是 HTTP 状态；
- 失败后保留失败记录并重新从 1/5 开始；
- 网络、渠道配对、依赖或人工操作未完成属于 `blocked`/`failed`，不能标记 `passed`；
- Mock、Stub 和本地单测证据标记为 `automated_preflight`，不能替代 `production_acceptance`。

## 6. 发布门禁

只有以下条件全部满足，才允许向项目主管提出正式发布申请：

- [ ] Stage 5B、5C、5D 已合并，且没有独立 `web_*` 业务状态机；
- [x] PR #57 的全部 7 个纠错阻断码均有自动化断言；
- [x] PR #60 候选 CI 6/6，完整测试无失败并完成 Claude Code 交叉评审；
- [ ] 唯一候选 commit 和依赖锁已冻结；
- [ ] 数据库/对象存储备份已校验，恢复演练成功；
- [ ] UI、RFQ、角色、审批、Plugin/SKILL、Email/LINE、Relay、Reversal、Token Guard 均连续 5/5；
- [ ] 当前手机 WeChat/Relay 五次真实闭环，且没有自动外发个人微信；
- [ ] 跨租户、越权、重复发送、秘密扫描和未批准外部模型测试全部通过；
- [ ] 监控、告警、回滚、恢复和交接文档完整；
- [ ] 产品、技术、运维和项目主管签字。

任何一项未满足，产品状态只能是“未发布/验收中”，不得使用“生产完成”“正式交付”或等价表述。

## 7. 基础设施硬约束

1. AIVAN/CTYun 服务器 `443` 和 `8443` 已被 SSH/MAIL 占用。Stage 6 不得停止、改绑、复用、代理接管或修改这些端口及其服务。
2. CTYun 访问中国大陆以外 IP 必须通过现有 `abcdyi-sin` 新加坡桥接；不得为测试或发布建立直连绕过。
3. 部署必须复用已批准的端口、反向代理和进程/容器入口；新端口或入口属于独立变更，需要运维批准。
4. MySQL、对象存储、邮件、LINE、OpenClaw、Qwen/Ollama 和其他凭据只由授权 Secret Store/环境注入；文档、代码、测试和证据不得含真实值。
5. Qwen API Key 不是私域基线依赖；如确需外部 API，必须提交独立数据最小化和成本审批，不得阻塞本地 Qwen/Ollama 基线。
6. 未经明确生产部署授权，Stage 6 PR 只交付代码、文档和本地/CI 证据，不主动修改服务器、数据库或渠道配置。

## 8. 回滚与事故处理

- 应用回滚：切回已验证上一候选版本，保留新增审计/纠错/回执表，不执行破坏性降级；
- 数据回滚：只有恢复演练通过且获得批准时，才从维护窗口前备份恢复；
- 渠道事故：立即停止新发送队列，不伪装撤回已发送内容，生成更正草稿并走正常审批；
- 租户或鉴权事故：立即 fail-closed、保留证据、轮换相关凭据并执行影响审计；
- Token Guard/模型事故：停止新模型任务，保留服务健康入口和非模型业务路径；
- 任何回滚均记录操作者、授权、时间、候选版本、原因、影响和验证结果。

## 9. Stage 6 首批开发任务

### 6A-1 纠错阻断码覆盖

为 Claude Code 指出的六个缺口增加专门测试，逐项验证 `automatic_reverse_allowed=false`、准确 blocker 名称、物化状态未改变和没有纠错副作用。

### 6A-2 连续验收执行器

提供安全的本地/CI 执行器：固定五次、追加 JSON 证据、记录锁文件摘要、失败归零语义、区分 preflight 与 production evidence，并拒绝把缺失外部证据当作通过。

### 6A-3 追踪矩阵

建立 FR/Stage → 实现 → 测试 → 自动证据 → 生产证据 → 状态 → 责任人的矩阵。Stage 5B–5D 初始状态必须为 `not_delivered`。

## 10. Definition of Done

Stage 6 只有在同一候选版本上同时完成业务闭环、渠道真实回执、五次连续验证、安全与租户测试、备份恢复、容量监控、文档交接和主管签字后才算完成。

完成 Stage 6A 仅代表“发布验收底座可用”，不代表 Stage 6 完成；完成代码 CI 也不代表生产发布。

## 11. 项目主管审批

- [ ] 批准 Stage 6 分段和发布门禁
- [ ] 确认 Stage 5B–5D 仍为发布前置依赖
- [ ] 批准 Stage 6A 自动验收底座开发
- [ ] 指定产品、技术、运维和渠道验收责任人
- [ ] 另行批准 CTYun 部署与维护窗口
- [ ] 另行批准正式发布

主管签名：________________________  日期：________________

审核意见：________________________________________________________________

