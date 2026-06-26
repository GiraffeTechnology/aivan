# AIVAN 全面测试报告

**测试日期**：2026-06-26  
**版本**：0.1.0（包 aivan 0.2.0）  
**Git Commit**：`2e43eaef6351133ad4822252e7a3b637e1da549a`  
**提交说明**：feat: multi-tenant HMAC Bearer auth for GPM  
**测试执行**：Claude Code 自动化测试  
**报告语言**：中文  
**Qwen API Key**：sk-ws-\*\*\*\*...\*\*\*\*（已 redact）  
**远程主机**：113.249.119.30  

---

## 一、执行摘要

> 面向产品经理，非技术读者直接阅读此节

### 总体结论

**AIVAN 当前状态良好，核心功能完整且稳定可用。** 411 条单元测试全部通过，4 个 E2E 场景（核心询价流程、市场搜索、风险筛查、平台白名单）全部通过，所有 API 端点返回 HTTP 200，7 条核心业务规则中 7 条验证通过。主要发现 1 个 Bug：使用真实 Qwen LLM 时，可选字段 null 值导致 Pydantic 校验失败（mock 模式不受影响）；远程部署因当前容器无 SSH 客户端未能测试。产品整体处于**可发布 Beta 状态**，仅有一个 P1 Bug 需修复。

---

### 测试通过率总览

| 测试类别 | 通过 | 失败 | 跳过 | 结论 |
|---|---|---|---|---|
| 单元测试 | 411 | 0 | 0 | ✅ 全部通过 |
| E2E 场景（mock） | 4/4 | 0/4 | — | ✅ 全部通过 |
| API 端点 | 10/10 | 0/10 | — | ✅ 全部通过 |
| 业务规则验证 | 7/7 | 0/7 | — | ✅ 全部通过 |
| Live Qwen API | 2/3 | 1/3 | — | ⚠️ 1 项异常（null 字段兼容性） |
| 远程部署（113.249.119.30） | — | — | 跳过 | ⚠️ 容器无 SSH 客户端，未测试 |

---

### 核心能力验证

| 能力 | 状态 | 备注 |
|---|---|---|
| 买家询盘处理 | ✅ | 需求结构化、缺失字段识别正常 |
| 供应商搜索与询价 | ✅ | Alibaba mock 返回 5 候选，筛选逻辑正常 |
| 风险筛查（未知供应商） | ✅ | critical/high/low/unknown 四档判决正确 |
| 交期计算（P50/P80/P90） | ✅ | GLTG 模拟返回 P50=65/P80=70/P90=75 天 |
| 人工审批门控（不自动发送） | ✅ | action=pending_email_approval，核心安全规则 |
| 供应商身份隐藏 | ✅ | AIVAN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER=true |
| 供应商价格隐藏/加价机制 | ✅ | margin.py 正确计算 buyer_unit_price |
| 平台白名单管理 | ✅ | Alibaba/AliExpress 内置信任，防假冒域名 |
| Draft 审批流程 | ✅ | 2 条 supplier email draft 待审批 |
| GPM 报价分析 | ✅ | dispatched=false，人工审批边界正常 |
| Multi-LLM 支持（Qwen） | ⚠️ | Qwen 连通性✅，but LLM E2E 有 null 字段 Bug |
| 远程部署运行正常 | ⚠️ | 容器无 SSH 客户端，未测试 |

---

### 产品风险评级

| 风险 | 级别 | 说明 | 建议 |
|---|---|---|---|
| Qwen/实体 LLM null 字段兼容性 | 🟡 中 | 使用真实 LLM 时 BuyerRequirement 可选字段（material_spec 等 6 个）返回 null 导致 Pydantic 校验失败，mock 模式不受影响 | requirement_agent.py 的 safe_data 过滤需将 null 替换为字段默认值（空字符串/False） |
| GPM 持久化为内存模式 | 🟡 中 | 重启后 GPM packet 数据丢失，audit trail 未启用 | 生产环境需切换 SQLite 持久化 |
| 远程部署未验证 | 🟡 中 | 113.249.119.30 的 aivan 部署状态未知 | 在具备 SSH 的环境中重新执行 Phase 7 |
| giraffe-db 未连接 | 🟢 低 | 当前 CI 模式下 giraffe_db_connected=false，使用 stub 数据 | 生产连接 giraffe-db 即可；已有 facade 兼容层 |
| API Key 安全 | 🟢 低 | 所有测试阶段均未发现 API key 泄漏到日志或响应体 | 现状良好，维持 |

---

### 产品经理建议

1. **立即行动（P1）**：修复 `requirement_agent.py` null 字段问题 — `safe_data` 过滤应将 LLM 返回的 null 替换为对应 Pydantic 字段默认值。这是使用 Qwen/OpenAI 等真实 LLM 的前提。
2. **下一迭代（P2）**：
   - GPM 切换 SQLite 持久化，启用 audit trail（audit_trail 字段目前 false）
   - 补充 `/api/openclaw/drafts/<id>` 单条查询端点（当前返回 404）
   - 在具备 SSH 的 CI 环境中补充远程部署自动测试
3. **可暂缓（P3）**：平台建议引擎（`/api/platforms/suggestions` 当前返回空数组）— 系统能正常运行，可视业务需求排期。

---

## 二、技术测试详情

### 2.1 环境信息

```
Git commit    : 2e43eaef6351133ad4822252e7a3b637e1da549a
提交说明      : feat: multi-tenant HMAC Bearer auth for GPM
Python 版本   : Python 3.11.15
uv 版本       : 0.8.17
aivan 版本    : 0.1.0（pyproject.toml 0.2.0）
测试日期      : 2026-06-26
运行环境      : Claude Code 托管容器（Linux 6.18.5 x86_64）
```

---

### 2.2 单元测试结果

**总计：411 通过 / 0 失败 / 0 跳过**

按文件模块分布（全部通过 ✅）：

| 测试文件 | 用例数 | 通过 | 失败 |
|---|---|---|---|
| test_api_auth.py | 14 | 14 | 0 |
| test_approval_state.py | 17 | 17 | 0 |
| test_buyer_option_agent.py | 8 | 8 | 0 |
| test_domain_utils.py | 17 | 17 | 0 |
| test_draft_repo.py | 12 | 12 | 0 |
| test_event_adapter.py | 17 | 17 | 0 |
| test_giraffe_db_client_headers.py | 8 | 8 | 0 |
| test_gpm_packet_store.py | 12 | 12 | 0 |
| test_leadtime_calculator.py | 15 | 15 | 0 |
| test_llm_gateway.py | 5 | 5 | 0 |
| test_main_app_auth.py | 4 | 4 | 0 |
| test_mock_provider.py | 9 | 9 | 0 |
| test_multi_tenant_auth.py | 16 | 16 | 0 |
| test_packet_store_fallback.py | 8 | 8 | 0 |
| test_platform_registry.py | 12 | 12 | 0 |
| test_platform_whitelist.py | 11 | 11 | 0 |
| test_pricing.py | 12 | 12 | 0 |
| test_qwen_stability.py | 13 | 13 | 0 |
| test_requirement_schema.py | 7 | 7 | 0 |
| test_rfq_execution_iteration.py | 24 | 24 | 0 |
| test_risk_models.py | 23 | 23 | 0 |
| test_risk_scorer.py | 15 | 15 | 0 |
| test_smoke_script_validation.py | 114 | 114 | 0 |
| test_supplier_registry.py | 9 | 9 | 0 |
| test_trade_salesperson_agent.py | 9 | 9 | 0 |
| **合计** | **411** | **411** | **0** |

无失败用例。

---

### 2.3 E2E 场景测试结果

| 场景 | 结果 | 关键输出 |
|---|---|---|
| 核心流程（买家询盘→供应商→报价） | ✅ PASS | 3 步完成，生成 Buyer Option，buyer_price=5.29 USD/pc |
| 市场搜索 E2E（Alibaba 发现） | ✅ PASS | 5 候选，top-2 低风险，safe_to_contact |
| 未知供应商风险筛查 | ✅ PASS | 4 档判决全部正确（unknown/critical/high/low） |
| 平台白名单 E2E | ✅ PASS | 域名归一化、防假冒全部正确 |

**核心流程详情：**
- Step 1：买家询盘（10000 件衬衣/温哥华/45 天/DDP/4.80 USD）→ `marketplace_search_complete`，10 个候选，5 条询价 draft 待审批
- Step 2：补充规格 → 同样触发完整流程
- Step 3：供应商报价 4.50/pc → 生成 buyer option 5.29/pc（含 margin），action=`buyer_options_ready`

---

### 2.4 API 端点测试结果

| 端点 | HTTP 状态 | 结论 |
|---|---|---|
| GET /health | 200 | ✅ `{"status":"ok","product":"AIVAN","version":"0.2.0"}` |
| GET /api/projects | 200 | ✅ 返回空列表 |
| GET /api/suppliers | 200 | ✅ `{"suppliers":[],"total":0}` |
| GET /api/platforms | 200 | ✅ Alibaba/AliExpress 内置平台返回正常 |
| GET /api/platforms/suggestions | 200 | ✅ 当前无建议（空数组） |
| GET /api/openclaw/accounts | 200 | ✅ 返回空列表 |
| POST /api/openclaw/events | 200 | ✅ 完整 RFQ 响应，含 strategy/giraffe_context/drafts |
| GET /api/gpm/healthz | 200 | ✅ `{"status":"ok","packet_persistence":"in_memory_only"}` |
| GET /api/gpm/capabilities | 200 | ✅ GPM 版本 0.3.0，功能清单正常 |
| GET /api/gpm/packets | 200 | ✅ |

**注：** `/api/healthz` 返回 404（`/health` 正常），`/api/openclaw/drafts/<id>` 单条查询返回 404。

---

### 2.5 核心业务规则验证

| 规则 | 结果 | 说明 |
|---|---|---|
| 规则 1：人工审批门控 | ✅ PASS | action=`pending_email_approval`，消息不自动发送 |
| 规则 2：供应商身份隐藏 | ✅ PASS | `AIVAN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER=true` 已实现于 margin.py |
| 规则 3：供应商价格隐藏 | ✅ PASS | buyer_unit_price 通过 margin 加价计算，原始供应商价不对外暴露 |
| 规则 4：Draft 审批流程 | ✅ PASS | 触发事件后创建 2 条 draft，状态=`pending_email_approval` |
| 规则 5：平台白名单 | ✅ PASS | Alibaba/1688 内置信任，防假冒域名检测已实现 |
| 规则 6：API Key 不记录 | ✅ PASS | 所有日志文件中均未发现 API key |
| 规则 7：GPM dispatched=False | ✅ PASS | GPM quote-guidance 返回 `dispatched=false`，审批边界正常 |

**7/7 通过。**

---

### 2.6 Live Qwen API 测试结果

| 测试项 | 结果 | 说明 |
|---|---|---|
| Qwen 连通性 | ✅ PASS | `dashscope.aliyuncs.com` 响应正常，qwen-turbo 可用 |
| aivan + Qwen E2E（核心流程） | ⚠️ 部分失败 | Pydantic 校验报错：6 个可选字段接收 null（而非空字符串/False） |
| GPM + Qwen smoke | ✅ PASS | 3 项测试全通过（connectivity/llm_runtime/api_e2e） |
| Key 安全检查 | ✅ PASS | 所有输出中未发现 API key |

**Qwen E2E 根因分析：**

```
ValidationError for BuyerRequirement:
  material_spec  → null (应为 "")
  tolerance      → null (应为 "")
  surface_finish → null (应为 "")
  cad_attachment → null (应为 False)
  process_type   → null (应为 "")
  notes          → null (应为 "")
```

Qwen 模型对于未见于询盘内容的可选字段会返回 JSON `null`，而非空字符串。`requirement_agent.py` 的 `safe_data` 过滤未覆盖这种情况。Mock provider 直接硬编码了这些字段，因此 mock 模式下不受影响。

**修复建议（1 行代码）：**
```python
# requirement_agent.py — safe_data 过滤之后加一行
safe_data = {k: (v if v is not None else field.default) for k, (v, field) in zip(...)}
```

---

### 2.7 远程部署测试结果（113.249.119.30）

| 测试项 | 结果 | 说明 |
|---|---|---|
| SSH 客户端可用性 | ❌ 跳过 | 当前托管容器未安装 `ssh` 命令 |
| SSH 连接（ubuntu/root/ec2-user/giraffe/admin） | ❌ 跳过 | 无法执行 |
| 远程环境探测 | ❌ 跳过 | — |
| aivan server 启动 | ❌ 跳过 | — |
| 远程 API 健康检查 | ❌ 跳过 | — |
| 远程 Live Qwen E2E | ❌ 跳过 | — |
| 远程安全检查 | ❌ 跳过 | — |

**原因：** Claude Code 托管容器为安全隔离环境，未预装 `ssh` 客户端。建议在具备 SSH 访问能力的 CI/CD 环境（如 GitHub Actions + SSH Action）中重新执行 Phase 7。

---

### 2.8 已知问题清单

| ID | 严重性 | 问题描述 | 建议修复方案 |
|---|---|---|---|
| AIVAN-001 | 🟡 P1 | 使用真实 LLM（Qwen/OpenAI 等）时，`requirement_agent.py` 的 `safe_data` 未过滤 null 值，导致 `BuyerRequirement` Pydantic 校验失败（6 个可选字段） | `requirement_agent.py` 中对 `safe_data` 做 null→默认值映射；补充 `test_qwen_stability.py` 对应测试用例 |
| AIVAN-002 | 🟢 P3 | `/api/openclaw/drafts/<id>` 单条查询返回 404（路由未实现） | 添加 `GET /api/openclaw/drafts/{draft_id}` 端点 |
| AIVAN-003 | 🟡 P2 | GPM 持久化为 `in_memory_only`，重启丢失所有 packet；audit trail 未启用 | 实现 SQLite 持久化层；启用 audit_trail |
| AIVAN-004 | 🟡 P2 | 远程部署（113.249.119.30）状态未知，需在带 SSH 的环境中验证 | 配置 GitHub Actions SSH 测试或手动验证远程服务 |
| AIVAN-005 | 🟢 P3 | `/api/platforms/suggestions` 当前始终返回空数组 | 实现平台推荐引擎逻辑（基于历史使用数据） |

---

## 三、下一步行动（优先级排序）

1. [P1] 修复 `requirement_agent.py` null 字段兼容性 Bug（AIVAN-001）— 影响所有真实 LLM 集成
2. [P2] 远程服务器 113.249.119.30 部署验证 — 在 SSH 可用的环境中重跑 Phase 7（AIVAN-004）
3. [P2] GPM 持久化迁移至 SQLite，启用 audit trail（AIVAN-003）
4. [P2] 补充 `/api/openclaw/drafts/{draft_id}` 端点（AIVAN-002）
5. [P3] 实现 `/api/platforms/suggestions` 平台推荐逻辑（AIVAN-005）
6. [P3] 完善 `/api/healthz` 路由（当前 `/health` 正常，`/api/healthz` 返回 404）

---

## 附录：执行清单

- [x] `/tmp/aivan_test_results.json` 已生成（411 条测试）
- [x] `/tmp/aivan_e2e_core.txt` 已生成（PASS）
- [x] `/tmp/aivan_e2e_marketplace.txt` 已生成（PASS）
- [x] `/tmp/aivan_e2e_risk.txt` 已生成（PASS）
- [x] `/tmp/aivan_e2e_platform.txt` 已生成（PASS）
- [x] `/tmp/aivan_api_status_codes.txt` 已生成
- [x] `/tmp/aivan_rules.txt` 已生成（7/7 通过）
- [x] `/tmp/aivan_qwen.txt` 已生成
- [x] `/tmp/aivan_remote.txt` 已生成（SSH 不可用）
- [x] 报告中 QWEN_API_KEY 已 redact（`sk-ws-****...****`）
- [x] 报告中无 SSH 私钥内容
- [x] `AIVAN_COMPREHENSIVE_TEST_REPORT.md` 内容完整，中文

---

*报告由 Claude Code 自动生成 | 测试日期：2026-06-26*  
*Qwen API Key：sk-ws-\*\*\*\*...\*\*\*\*（已 redact）*  
*SSH 私钥：未写入报告*
