# AIVAN Stage 7 交付闭环 PRD V1.0

文档状态：独立基准稿

产品阶段：Stage 7（交付闭环、生产候选与受控上线）

审计基线：`GiraffeTechnology/aivan` `main@5d975349ac74df394344aa99f947cb043e40c833`

基线时间：2026-08-06（Asia/Shanghai）

适用产品：AIVAN Core、myAIVAN/myaivan.com、AIVAN-OpenClaw Plugin、AIVAN-OpenClaw SKILL、Email/LINE/微信/旺旺通道、CTYun AIVAN 运行环境

审批角色：项目主管、产品负责人、安全负责人、运维负责人

---

## 1. 文档目的

Stage 7 不是对 Stage 1–6 的重新命名，而是把“已有代码、真实可用、可安全
部署、可审计验收”收敛为同一个交付事实。本 PRD 同时承担：

1. 记录截至基线提交的已交付能力和全部已知差距；
2. 明确多重角色转换、AIVAN-OpenClaw SKILL、微信端和 myAIVAN 的统一
   产品边界；
3. 把安全、依赖、CI、迁移、生产基础设施和真实通道证据纳入发布门禁；
4. 给 Codex/Claude Code 提供可连续执行、可交叉评审的阶段任务；
5. 给项目主管提供唯一的 Stage 7 验收与签署基准。

本文中的“完成”只表示有可复现证据满足对应验收条件。文档、Mock、测试
替身、代码结构、工作流绿灯或单次人工演示均不能替代真实生产验收。

---

## 2. P0 约束与授权边界

以下规则优先于任何功能、进度或自动化便利性：

1. **无明确逐次授权，禁止外发。** 不得向 Email、LINE、微信、旺旺或其他
   第三方通道自动发送代理回复、审批提醒、报价、询盘或测试消息。
2. 识别出账号所有人、认证参与者、会话角色或 `approved` 状态，不等于获得
   新一次外发授权；每个外发动作必须有可追溯的审批/授权记录。
3. 微信和旺旺个人 IM 只允许“引导中继”：审批、复制/打开目标、人工发送、
   回填确认。AIVAN 不得伪装成平台原生自动发送。
4. 未获生产变更授权，不得部署、迁移、写生产数据库、修改 DNS/CDN、反向
   代理、容器/进程、系统服务、监控或 Secret。
5. AIVAN CTYun 服务器的 `443`/`8443` 已被 SSH/MAIL 占用，AIVAN 与
   myAIVAN 不得修改、监听、复用、转发或重启相关服务。
6. CTYun 访问中国大陆以外 IP 必须经过 `abcdyi-sin` 新加坡桥接，不得直连。
7. 密码、私钥、Access Key、Secret Key 与 Token 仅由授权 Secret Store
   注入；仓库、PR、日志、测试夹具和验收证据只能记录位置、状态或摘要。
8. Codex 与 Claude Code 默认交叉 PR/CI；同一 GitHub 账号可合并，但除非
   特别授权，作者不能以自己未复核的结论替代另一执行方的评审。

---

## 3. 基线盘点结论

### 3.1 已交付且可继承

| 阶段 | 已有能力 | Stage 7 继承结论 |
|---|---|---|
| Stage 1 | 统一请求入口、API 鉴权、Tenant/Trace/Idempotency 上下文 | 代码与测试存在；生产身份配置仍需验收 |
| Stage 2 | Buyer/Supplier/Sales/Approver/Admin 等角色模型、会话角色、RBAC、Case 状态 | 多重角色域模型已建立；UI 角色切换与真实账号映射未闭环 |
| Stage 3 | AIVAN-OpenClaw Plugin、独立 SKILL、6 个 Gateway 工具、生命周期与契约证据 | 工具面可用；旧 Harness 会把结果自动变成 IM assistant reply，属 P0 |
| Stage 4 | 通道能力矩阵、微信/旺旺 guided relay、审批与 relay 核心记录 | 核心存在；真实手机五轮证据、准确状态语义仍缺失 |
| Stage 5A | 事件纠错/撤销、7 个阻断码专测、只存 SHA-256 证据、追加式 reversal | 核心机制交付；下游失效、纠正草稿与完整会话恢复未交付 |
| Stage 6A | 五次连续运行、失败清零中止、preflight 与 production acceptance 结构隔离、环境 profile | 机制已证明；CI/候选冻结/JS 锁摘要/生产证据尚未完整 |

基线回归在显式 UTF-8 环境下为 `760 passed, 2 skipped`；Windows 默认 GBK
下曾因测试读取 Markdown 未指定 UTF-8 而在收集阶段失败。两个 skip 为需真实
GLTG 服务的 live integration，不可解释为已通过。

### 3.2 P0 差距

#### P0-01 未授权外发路径

- `rfq_execution._send_user_control_notification` 过去在识别 owner 后直接创建
  `approved` 草稿并调用 OpenClaw，绕过逐次人工授权。
- OpenClaw Harness 过去把 Core 的 `reply_text` 放入 `assistantTexts`，导致
  微信等个人 IM 自动回复；失败降级文本也会自动回复。
- `AIVAN_REQUIRE_HUMAN_APPROVAL` 仅定义，不能作为完整的逐次授权证据。

Stage 7A 要求：所有 user-control 内容只创建 `pending_approval` 草稿；Harness
对已处理 inbound 返回“已处理但无外发文本”，禁止模型 fallback；真实发送只能
从独立审批/引导中继状态机发生。

#### P0-02 过期且危险的部署工作流

旧 `.github/workflows/deploy-server.yml` 包含过期主机 `113.249.119.30`、root、
`sshpass`、关闭主机校验、旧目录、端口 8000、`pkill`、原地重启 Gateway、
可跳过测试且没有 checkout/候选 SHA/备份/迁移/回滚/Environment 审批。它与
当前运维入口及端口、桥接约束冲突。

Stage 7A 先将其隔离为“只登记、不部署”的无副作用工作流。任何恢复部署能力
的 PR 必须进入 Stage 7F 独立审批。

#### P0-03 myAIVAN 尚非交付 UI

当前 `/app` 是 Demo 管理页，曾硬编码会话、客户和 channel account；请求未
完整携带 API key、tenant、actor、role、conversation role、trace、idempotency
等上下文；缺少共享 Core 会话 API 和角色化工作台。主要缺项：

- 会话、消息、参与者、角色转换、审批、审计、导出、上传的统一 API；
- Sales/Approver/Admin/Supplier/Buyer 角色视图和受控切换；
- 审批卡、引导中继卡、纠错卡、真实 receipt、失败原因和依赖健康；
- 附件/语音占位、Markdown 导出、键盘与屏幕阅读器可访问性；
- 移动端布局及 myaivan.com 部署证据。

旧页面还把 API 数据直接插入 `innerHTML`，存在 DOM XSS；“Approve & Send”
把审批和发送错误合并；“all data stays on your machine”与服务/通道事实不一致。

#### P0-04 Stage 5C 真实通道未交付

- LINE 只有 registry 能力声明，没有可验证 adapter、receipt 和失败分类；
- Email 只有特殊 real-test 路径或通用 OpenClaw 路径，没有统一 receipt ledger；
- Relay confirm 的历史状态可能记录成 `sent` 而非 `relayed`；
- 微信没有当前候选提交上的真实手机五轮入站、审批、中继和确认闭环。

#### P0-05 依赖与代码扫描

审计时 Dependabot 有 24 个 open alert（7 High、15 Moderate、2 Low），主要
来自 OpenClaw Plugin 的 npm 开发依赖；9 个 Dependabot PR（#40、#41、#42、
#43、#44、#46、#47、#49、#50）CI 为绿但未合并。CodeQL 未启用，main 规则
未要求 code scanning；仓库级 Actions full-SHA enforcement 未开启。

发布前必须：High=0；Moderate 有修复或主管签署的时限化例外；生成并审阅
Python/JavaScript CodeQL 结果；所有第三方 Action 固定完整 SHA。

#### P0-06 数据库与部署声明不一致

运维配置包描述 MySQL/隧道，仓库运行和部署示例仍为 SQLite，Python 依赖未见
MySQL driver；`create_all` 不能替代升级。Stage 1/2/4/5A 有四个手工迁移脚本，
没有统一编排、当前生产 schema 版本或恢复演练证据。

生产候选必须只选择一个被批准的数据库 profile，提供迁移前检查、顺序、幂等、
备份、恢复、回滚和 schema version 证据，不得在部署时临时猜测。

#### P0-07 无生产验收证据

目前没有同一冻结候选上的 Stage 5B–5D、真实 Email/LINE receipt、当前手机微信
relay 5/5、CTYun 部署、桥接、端口安全、备份恢复、监控容量和主管签署证据。

#### P0-08 GitHub 治理未闭环

审计观察：单一管理员账号；2FA 当时未启用且 GitHub 提示 2026-08-17 截止；
main ruleset 已限制删除/强推并要求 PR、状态检查、Code Owners、会话解决和线性
历史，但 required approvals=0、签名提交关闭、最近推送者独立审批关闭、未要求
code scanning；Actions 允许全部，默认 token 只读，Actions 不可批准 PR；没有
GitHub Environments。

Stage 7E/F 需由管理员核验 2FA、审批数、交叉评审、Environment、扫描门禁、
Secret/协作者/App 权限。代码 PR 不能冒充这些控制面设置已完成。

### 3.3 P1 差距

1. Stage 5A 只恢复 Case state/strategy；未生成下游失效集合、补偿任务和纠正草稿。
2. `CaseMessage` 主要保存摘要；当前 requirement JSON 可能覆盖原 RFQ，无法生成
   完整会话与逐版本事实导出。
3. 附件主要是 `attachments_json`，没有对象存储、病毒/类型/大小检查、上传授权、
   保留和删除策略。
4. CORS 曾为 `*` + credentials + 全方法/全头；生产必须精确 allowlist。
5. Stage 6 runner 未进入 CI artifact，锁摘要不含 `package-lock.json`，candidate
   commit 接受自由字符串。
6. Stage 6 文档仍可能引用旧 baseline，tracker 未按实际勾选。
7. 没有 `/metrics`、告警、容量阈值、备份恢复工具和发布 provenance。
8. 文档默认 Qwen `qwen3.5:2b`，用户给出的 AIVAN 实机当前为 `qwen3.5:9b`；
   必须由环境 profile 和实机证据确认，不能在代码中假定。
9. Windows 文档契约测试未显式 UTF-8；两个 GLTG live tests skip；giraffe-db
   scanner 在跨仓 token 不存在时跳过。
10. PR #36 为 draft/reference-only，不得误合并；Issue #6 的历史描述可能陈旧，
    但验收结论必须以当前候选代码和证据为准。
11. 本地曾存在 Stage 5A 脏分支与 stale refs；开发过程必须使用隔离工作树，禁止
    以未提交本地状态冒充 GitHub main。

---

## 4. Stage 7 产品目标

### 4.1 业务目标

1. 一个交易 Case 可同时承载 Buyer、Supplier、Sales、Approver、Admin 等参与者，
   角色转换不改变历史事实、不跨 Tenant、不自我提权。
2. AIVAN-OpenClaw SKILL 只承担意图路由、Core 调用和受控工具；不复制业务逻辑、
   不保管平台凭据、不产生未经审批的外发。
3. myAIVAN 成为 Core 的角色化运营界面，而不是独立数据孤岛或 Demo 包装。
4. Email、LINE 和个人 IM 使用统一 Draft → Approval → Delivery/Relay → Receipt
   状态模型，每一次变更都有 Actor、Role、Trace、Authorization Basis 和摘要。
5. 同一冻结候选在 CI、candidate preflight 和授权 production acceptance 中可追溯。

### 4.2 非目标

- 不绕过第三方登录、CAPTCHA、反爬、平台授权和速率限制；
- 不在仓库保存第三方账号凭据；
- 不承诺未授权的全自动个人 IM；
- 不以 Demo、Mock 或 preflight 代替生产通道与生产基础设施验收；
- 不在 Stage 7A–7E 变更 CTYun 生产环境。

---

## 5. 统一领域与状态契约

### 5.1 身份分层

每个请求必须区分：

- Service Identity：认证的 AIVAN/OpenClaw/myAIVAN 调用方；
- Participant Identity：外部消息参与者的稳定伪名标识；
- Business Role：buyer、supplier、sales、approver、admin；
- Conversation Role：buyer_thread、supplier_thread、internal_thread；
- Execution Mode：manual、approval、relay、automated_preflight；
- Authorization Basis：审批记录、受控策略或明确授权引用。

客户端提供的 role 只是声明，不能授予内部能力。Role switch 必须通过 Core API
验证权限并追加审计事件；供应商/买家线程不能读取另一方敏感事实。

### 5.2 外发状态机

规范状态：

`draft → pending_approval → approved → delivery_pending → sent|relayed|failed`

- `approved` 只证明内容/动作获批，不等于已发送；
- guided relay 使用 `approved_pending_send/relay_ready → relayed`；
- `sent` 必须有 adapter receipt；`relayed` 必须有人工确认；
- 失败必须保留稳定 failure code、retryable 和安全摘要；
- 撤销/纠正不得删除原记录，必须追加 superseded/reversal/correction 链。

### 5.3 Receipt 最小字段

`receipt_id, tenant_id, case_id, draft_id, channel, delivery_mode,
adapter_name, provider_message_digest, status, actor_id, actor_role,
authorization_id, source_trace_id, attempted_at, completed_at, failure_code,
retryable, evidence_digest`。

禁止在 receipt/evidence 中保存密码、Token、私钥、完整原始输出或不必要的 PII。

---

## 6. 分阶段任务与验收目标

### Stage 7A — 失败关闭与部署隔离（P0）

任务：

- [x] owner resolution 不再触发 user-control 自动发送；只生成待审批草稿；
- [x] OpenClaw Harness 默认不返回 `assistantTexts`，并阻止自动模型 fallback；
- [x] 日志不打印 Core reply 内容，只记录长度和结构字段；
- [x] 旧部署工作流替换为无 Secret、无远端连接、无变更的 quarantine record；
- [x] 部署 SOP 写入 CTYun、Singapore bridge、443/8443 和授权约束；
- [x] CORS 改为精确 allowlist，production 无配置时拒绝跨域，拒绝 `*`；
- [x] Demo UI 的 API 数据插值转义、ID 编码、凭据仅保存于 sessionStorage；
- [x] “Approve & Send”拆分为准确的审批/relay/delivery 结果；
- [x] Windows 文档契约测试显式 UTF-8；
- [x] Claude Code 对 PR #59 的 P0 路径完成交叉 CI/评审。

Stage 7A.1 复审增补（PR #59 合并后发现）：

- [x] GPM 生产认证复用可信请求上下文，禁止仅凭 `X-Tenant-ID` 写入；
- [x] 生产 GPM 在 giraffe-db 缺失、不可用或非 durable 时失败关闭；
- [x] 实际审批 API 的发送失败落入 `send_failed` 并可重试；
- [x] 数据库默认名统一为 `aivan.db`，旧 `aiven.db` 兼容且双文件歧义失败关闭；
- [x] 生产模板补齐租户、CORS、显式数据库、GPM 持久化与 qwen3.5:9b 现场值；
- [x] 旧 CTYun 执行手册替换为无命令 quarantine notice；
- [x] Stage 7A.1 PR #60 已由 Claude Code 完成交叉 CI/评审，CI 6/6 通过并合并为 `61e456688952cda6e09574b33413b4eb1f84aac3`。

验收：新增安全回归测试通过；代码中不存在 Harness `assistantTexts: [replyText]`；
部署 workflow 不含 SSH/Secret/远端变更；默认生产 CORS 无 wildcard。

### Stage 7B — Shared Core API 与事实保存

任务：

- [ ] 提供分页的 cases/conversations/messages/participants/approvals/audit API；
- [ ] 所有 API 强制 Tenant、Actor、Role、Trace，写请求强制 Idempotency-Key；
- [x] 实现受控 role switch 和角色可见性投影；
- [x] 保存原始 inbound message 的受控内容引用与不可变 digest/version；
- [x] 提供 Markdown/JSON 审计导出，包含版本和纠错链；
- [ ] 实现附件上传授权、对象存储接口、类型/大小/恶意内容检查和生命周期；
- [ ] Stage 5A 补上下游 invalidation、补偿任务与 correction draft。

验收：跨 Tenant/跨角色负测、重复请求、并发审批、纠错后旧草稿失效、导出一致性
全部通过；迁移可重复、可回滚并有备份恢复测试。

### Stage 7C — Email/LINE/个人 IM 适配器与 Receipt

任务：

- [ ] 定义统一 Adapter/Receipt/Failure Taxonomy 接口；
- [ ] Email adapter 仅在批准 allowlist 与授权窗口内发送并生成 receipt；
- [ ] LINE adapter 完成最小真实收发与 receipt；
- [ ] 微信/旺旺只实现 relay card、复制/打开目标、人工确认和 `relayed` 状态；
- [ ] retry 仅适用于幂等且明确 retryable 的动作；审批/拒绝不自动重试；
- [ ] 真实通道测试与普通业务数据隔离，自动清理测试数据但保留摘要证据。

验收：每通道成功、拒绝、超时、重复、撤销和部分失败测试；任何缺失授权都不得
产生网络调用；真实 receipt 可与冻结 candidate 和授权编号关联。

### Stage 7D — myAIVAN 交付界面

任务：

- [x] 建立登录/会话恢复与 Core identity bootstrap；
- [x] Case 列表、对话时间线、参与者和角色切换；
- [x] Approval、Relay、Correction、Receipt、Dependency Health 卡片；
- [ ] 附件/语音占位与上传进度、失败恢复；
- [ ] 审计筛选和 Markdown/JSON 导出；
- [ ] 移动端与桌面响应式、键盘、焦点、ARIA、对比度；
- [x] 删除硬编码 Demo 身份，开发演示必须显式标识 Mock；
- [ ] myaivan.com 构建产物与 Core API 版本固定到同一 candidate。

验收：五种角色端到端任务；无 DOM XSS；无浏览器持久保存 API key；移动真机
完成 inbound → draft → approval → relay/receipt → audit；UI 不夸大发送状态。

### Stage 7E — 候选冻结、安全与发布工程

任务：

- [x] Stage 6 runner 将 `package-lock.json` 纳入锁摘要；
- [x] CI/candidate profile 只接受完整 40 位 commit SHA；
- [x] CI 运行五轮并上传 digest-only evidence artifact；
- [x] 候选锁升级到 OpenClaw `2026.7.2-beta.7`，本地 `npm audit` 为 0；
- [ ] PR 合并后确认 GitHub Dependabot alerts 同步清零，并在稳定 2026.7.2
  发布后替换 prerelease、重跑相同门禁；
- [ ] Python/JavaScript CodeQL 工作流与扫描结果；
- [ ] main ruleset 要求交叉评审、所需 CI 和 code scanning；
- [ ] 仓库 Actions full-SHA enforcement、2FA、App/协作者权限复核；
- [x] 选择并固化数据库 profile，建立迁移编排器和 schema version；
- [ ] 生成 SBOM、构建 provenance、签名/摘要和 release manifest；
- [ ] `/metrics`、结构化日志、告警、容量和备份恢复演练；
- [ ] 更新 Stage 6 tracker/traceability 到最终 candidate。

验收：依赖与扫描门禁绿；无未处置 High；候选 SHA、锁、产物、迁移和证据一一
对应；CI artifact 不含 raw output/Secret/PII。

### Stage 7F — 授权生产上线与五轮验收

前置条件：必须另有明确生产授权；Stage 7A–7E 全部完成；GitHub Environment
审批生效。没有授权时本阶段保持 `blocked_by_authorization`，不得自动执行。

任务：

- [ ] 核验 CTYun AIVAN 目标、主机指纹、非 root 权限和固定目录；
- [ ] 核验 `443`/`8443` 零变更，记录部署前后端口/服务摘要；
- [ ] 核验所有境外依赖经 `abcdyi-sin`，并保留路由摘要；
- [ ] 执行备份、迁移、部署、健康、回滚可用性检查；
- [ ] 用当前实机环境 profile 记录 Qwen 模型（预期由现场确认 9B，不硬编码）；
- [ ] Email/LINE/微信真机各按授权范围执行真实测试；
- [ ] 同一 candidate 连续五轮 production acceptance；任何一轮失败立即清零；
- [ ] 项目主管、安全、运维和产品签署。

验收：五轮均成功；receipt、监控、备份恢复、桥接、端口和签署证据齐全。任何
跳过项均使 production acceptance 失败，不能记录为 passed。

---

## 7. Stage 6/7 证据契约

### 7.1 自动 preflight

只允许 `evidence_class=automated_preflight` 且 `production_acceptance=false`。
证据保存：完整 candidate SHA、environment profile、锁文件摘要、测试路径、次数、
返回码、持续时间和 stdout/stderr SHA-256。禁止保存 raw output 和环境变量值。

### 7.2 Production acceptance

必须使用结构上不同的 schema/签署流程，至少增加：deployment id、backup/restore、
migration version、port safety、bridge route、real receipt ids、monitoring window 和
sign-offs。自动 preflight 不得被重命名或复制为 production evidence。

### 7.3 连续五轮语义

只允许五次连续成功。任何失败：`consecutive_passes=0`、停止当前批次、修复后从
第一轮重跑。不能挑选五次历史成功拼接，也不能把 skip 计为成功。

---

## 8. 非功能要求

### 安全

- 默认拒绝、最小权限、Tenant 隔离、Server-side RBAC；
- 输出编码、CSP/CSRF 设计、精确 CORS、敏感日志脱敏；
- 供应链 Action 全 SHA、锁定依赖、High=0、扫描门禁；
- 审批与 delivery 分离，外发有逐次授权和幂等 receipt。

### 可靠性

- Core/adapter 超时、熔断、可重试分类和幂等；
- 数据迁移与恢复 RTO/RPO 由运维签署；
- 关键路径指标、日志、trace 和告警；
- 单次依赖故障不产生重复消息或错误状态。

### 性能与容量

- UI 常用列表 P95 目标 2 秒内（在批准的基线数据量）；
- 写操作及时返回稳定 trace/idempotency；
- 本地 Qwen 并发和 token guard 沿用受控上限，现场用 9B profile 重新压测；
- 容量结果必须声明硬件、模型、数据量和并发，不能跨环境外推。

### 可访问性与国际化

- 中文/英文业务字段不丢失；canonical facts 与展示语言分离；
- WCAG 2.1 AA 方向：键盘、焦点、标签、ARIA、对比度和错误提示；
- 移动端触控目标、断网/弱网和恢复状态可见。

---

## 9. 发布门禁

以下任一项不满足，Stage 7 不得宣布完成或生产可用：

1. 未授权外发测试失败或出现网络调用；
2. Stage 7A–7E 有未完成 P0；
3. 7 High Dependabot alert 未清零；
4. CodeQL/CI/依赖审查存在未处置阻断；
5. 数据库 profile、迁移、备份恢复不明确；
6. 443/8443 或 Singapore bridge 证据缺失；
7. Email/LINE/微信真实 receipt/relay 证据缺失；
8. production acceptance 不是同一冻结 candidate 连续五次成功；
9. GitHub Environment、交叉评审或项目主管签署缺失；
10. 证据含 Secret、原始敏感输出或不可核验的自由文本候选标识。

---

## 10. 当前实施状态（本 PRD 首次提交）

本次仓库内安全改动覆盖 Stage 7A 代码项、OpenClaw 安全锁更新和 Stage 7E 的候选证据链增强；均需
PR CI 与另一执行方评审后才可标记为 merged。Stage 7B–7D、依赖/CodeQL/GitHub
控制面和 Stage 7F 仍按本 PRD 继续，不得因本 PRD 或单个 PR 存在而宣称完成。

本次明确未执行：生产部署、数据库迁移、Secret 读取、Email/LINE/微信/旺旺
外发、DNS/CDN/反向代理修改、端口修改、服务重启和 GitHub 管理员控制面修改。

### 2026-08-10 状态校准

- Stage 7A/7A.1 已合并；原未勾选的交叉评审项已按 PR #60 事实更新。
- Stage 7B–7F 的未勾选项仍是未交付或待授权，不因自动化 preflight 通过而改变。
- 技术债清理候选新增安全日志、生产 GPM 无缓存、`relayed` 终态、模块体积预算以及
  Ruff/Mypy/Bandit/覆盖率门禁；在其 PR 合并前仅记为 candidate，不记为 delivered。
- Stage 7F 继续保持 `blocked_by_authorization`；443/8443 和 `abcdyi-sin` 约束不变。

### 2026-08-20 生产前部署校准

- 新增 Stage 7F 只读生产前门禁：候选必须为完整 40 位 SHA；核验生产配置结构、
  精确 CORS、固定 SQLite profile、Singapore bridge、443/8443 端口归属、锁摘要
  与当前 schema。证据固定为 `production_predeployment` 且
  `production_acceptance=false`，禁止把 predeployment 冒充生产验收。
- 新增 `STAGE7F_PREDEPLOYMENT_RUNBOOK.md`，明确备份校验、迁移 preview/apply
  授权、MyAivan 任务交接、回滚触发与证据边界。
- 2026-08-20 已恢复既有 AIVAN → `abcdyi-sin` 反向隧道并通过桥接 `/health`；
  AIVAN 443 仍由 nginx、8443 仍由 Stalwart 占用，均未重启或改绑。
- 上述仅关闭桥接与生产前门禁 gap。候选合并、数据库备份/迁移、UI 实机部署、
  `https://myaivan.com` 证书/路由、五轮生产验收、真实通道证据和主管签署仍须按
  Stage 7F 顺序完成，未完成项不得勾选。

---

## 11. 主管签署表

| 角色 | 姓名/账号 | 结论 | 时间 | 证据引用 |
|---|---|---|---|---|
| 产品负责人 |  |  |  |  |
| 安全负责人 |  |  |  |  |
| 运维负责人 |  |  |  |  |
| 交叉评审方 |  |  |  |  |
| 项目主管 |  |  |  |  |

允许的最终结论仅有：`accepted`、`accepted_with_time_bounded_exceptions`、
`rejected`。任何例外必须列出 owner、期限、风险、补偿控制和复核时间；P0 外发、
端口、桥接、Secret 与生产授权不得例外放行。
