# SOP: OpenClaw + AIVAN 集成部署

**版本:** 1.0 
**日期:** 2026-06-22 
**服务器:** 天翼云 ECS (成都) `113.249.119.30` 
**Workflow 文件:** `.github/workflows/deploy-server.yml`

---

## 概述

本 SOP 描述如何通过 **GitHub Actions** (`workflow_dispatch`) 将 OpenClaw AIVAN 插件部署到生产服务器，实现微信消息 → AIVAN 采购 AI 的完整路由，替代默认 Qwen 直接回复行为。

### 架构

```
微信用户 ──→ openclaw-weixin channel
              └─→ OpenClaw Gateway (port 80/443)
                   └─→ [openclaw-aivan plugin]
                         └─→ AIVAN FastAPI (localhost:8000)
                               └─→ 生成 RFQ 项目 / 采购草稿
```

---

## 前置条件

### 1. GitHub Secret 配置

进入 `https://github.com/GiraffeTechnology/aivan/settings/secrets/actions`，添加：

| Secret 名称 | 说明 |
|-------------|------|
| `SERVER_SSH_PASSWORD` | 服务器 root 密码 |

### 2. 天翼云安全组放行 SSH

GitHub Actions runner 需要从外部 SSH 到服务器端口 22。

**获取 GitHub Actions IP 段：**

```bash
curl -s https://api.github.com/meta \
  | python3 -c "
import sys, json
for cidr in json.load(sys.stdin).get('actions', []):
    print(cidr)
"
```

**在天翼云控制台操作：**

1. 进入「云服务器 ECS」→「安全组」→ 选中服务器绑定的安全组
2. 点击「入站规则」→「添加规则」
3. 协议：TCP | 端口：22 | 来源：逐条粘贴上述 CIDR

> **快捷方案（仅部署期间）：** 临时将端口 22 来源设为 `0.0.0.0/0`，部署完成后立即改回。

---

## Workflow 文件说明

文件路径：`.github/workflows/deploy-server.yml`

### 触发方式

**仅支持手动触发** (`workflow_dispatch`)，不会在代码 push 时自动运行。

### 输入参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `skip_tests` | 跳过烟雾测试（加快速度） | `false` |
| `target_host` | 目标服务器 IP | `113.249.119.30` |

### 部署步骤（共 8 步）

| Step | 操作 | 关键命令 |
|------|------|----------|
| `[1/8]` | SSH 连通性检测 | `ssh root@host 'echo ok'` |
| `[2/8]` | 编译 AIVAN 插件 | `npm install && npx tsc` |
| `[3/8]` | 安装插件到 OpenClaw | `openclaw plugins install <path>` |
| `[4/8]` | 注入 Gateway 环境变量 | 写入 `systemd override env.conf` |
| `[5/8]` | 启用插件 + 重启 Gateway | `openclaw config set` + `openclaw gateway restart` |
| `[6/8]` | AIVAN 服务守护进程化 | 创建并启动 `aivan.service` |
| `[7/8]` | 健康检查 | `curl /health` + `openclaw plugins list` |
| `[8/8]` | 烟雾测试 | `uv run python scripts/test_openclaw_*` |

---

## 部署操作流程

### Step 1 — 配置 Secret（一次性操作）

```
https://github.com/GiraffeTechnology/aivan/settings/secrets/actions/new
Name: SERVER_SSH_PASSWORD
Value: <服务器密码>
```

### Step 2 — 放行安全组

按上方说明在天翼云控制台添加 GitHub Actions IP 段入站规则（端口 22）。

### Step 3 — 触发 Workflow

1. 打开 Actions 页面：
   `https://github.com/GiraffeTechnology/aivan/actions/workflows/deploy-server.yml`
2. 点击右上角 **「Run workflow」**
3. 按需勾选 `skip_tests`，确认 `target_host` 正确
4. 点击绿色 **「Run workflow」** 按钮

### Step 4 — 监控运行

刷新页面，点击最新运行记录查看实时日志。预计总耗时 **5-10 分钟**。

每步均有明确标题和 `✓` 确认消息，失败会立即终止并标红。

---

## 成功标准

Workflow 最后一步（`Print success criteria`）自动输出：

```
╔══════════════════════════════════════════════════╗
║          SUCCESS CRITERIA VERIFICATION           ║
╚══════════════════════════════════════════════════╝
[1] AIVAN health:   PASS - {'status': 'ok', 'service': 'giraffe-agent'}
[2] Plugin enabled: PASS
[3] WeChat channel: openclaw-weixin: enabled, configured, running
[4] aivan.service:  active
[5] Gateway sees aivan: PASS (aivan in logs)
```

五项全部 `PASS` → 部署完成。

---

## 端对端验证

用测试买家微信账号发送：

> `帮我询价 10000 件白色纯棉衬衣，45 天内交温哥华`

**期望回复（AIVAN 生成）：**

```
已创建采购项目 RFQ-XXXXXXXX。

已识别：
  产品：白色纯棉衬衣
  数量：10000 件
  交期：45 天内
  目的地：温哥华

还缺：
  1. 尺码比例
  2. 面料克重
  ...
```

**如仍收到通用 Qwen 回复** → 插件路由未生效，见下方排查。

---

## 故障排查

### 插件安装后看不到（plugins list 为空）

```bash
# 检查插件注册目录
ls ~/.openclaw/plugins/ 2>/dev/null || ls ~/.local/share/openclaw/plugins/ 2>/dev/null

# 检查 openclaw config
openclaw config get plugins

# 重新安装
openclaw plugins install /opt/giraffe/giraffe-agent/integrations/openclaw-aivan-plugin
```

### aivan.service 启动失败

```bash
systemctl --user status aivan.service
journalctl --user -u aivan.service -n 50 --no-pager
```

常见原因：

| 现象 | 检查 |
|------|------|
| `uvicorn: not found` | `ls /opt/giraffe/giraffe-agent/.venv/bin/uvicorn` |
| 依赖缺失 | `cd /opt/giraffe/giraffe-agent && uv sync` |
| 数据库报错 | 确认 `GIRAFFE_DB_MODE=off` 已写入 service 文件 |
| 端口被占 | `lsof -i :8000` → `pkill -f uvicorn` |

### AIVAN 健康检查不通过

```bash
# 两个路径都试
curl http://localhost:8000/health
curl http://localhost:8000/api/health

# 查看 AIVAN 日志
journalctl --user -u aivan.service -f
```

### 消息仍走 Qwen（插件路由失效）

```bash
# 1. 确认插件的 event-handler 已注册
cat /opt/giraffe/giraffe-agent/integrations/openclaw-aivan-plugin/index.ts \
  | grep -A5 'event-handler\|forwardEvent'

# 2. 实时跟踪 Gateway 日志
journalctl --user -u openclaw-gateway.service -f \
  | grep -i 'aivan\|weixin\|forward\|plugin'

# 3. 确认环境变量已注入
systemctl --user cat openclaw-gateway.service | grep AIVAN
```

### WeChat 掉线 / pairing 丢失

```bash
openclaw channels status --probe
openclaw channels restart openclaw-weixin
openclaw pairing list openclaw-weixin

# 审批待确认配对码
openclaw pairing approve openclaw-weixin <CODE>
```

### Qwen/Dashscope 配置确认

```bash
openclaw config get agents
# 期望: memorySearch.enabled: false, model: dashscope/qwen-plus

journalctl --user -u openclaw-gateway.service -n 30 \
  | grep -i 'model\|provider\|openai\|qwen'
```

---

## 关键路径速查

| 资源 | 路径 |
|------|------|
| 插件 TypeScript 源码 | `/opt/giraffe/giraffe-agent/integrations/openclaw-aivan-plugin/index.ts` |
| 插件编译产物 | `/opt/giraffe/giraffe-agent/integrations/openclaw-aivan-plugin/dist/` |
| AIVAN FastAPI 入口 | `/opt/giraffe/giraffe-agent/api/main.py` |
| AIVAN systemd 服务 | `~/.config/systemd/user/aivan.service` |
| Gateway env override | `~/.config/systemd/user/openclaw-gateway.service.d/env.conf` |
| OpenClaw 全局配置 | `~/.openclaw/openclaw.json` |
| 烟雾测试 (买方) | `/opt/giraffe/giraffe-agent/scripts/test_openclaw_bside_invoke.py` |
| 烟雾测试 (供应商) | `/opt/giraffe/giraffe-agent/scripts/test_openclaw_mside_invoke.py` |
| Workflow 文件 | `.github/workflows/deploy-server.yml` (aivan repo) |

---

## 部署后安全组收缩

> **重要：** 部署完成后立即执行

在天翼云控制台 → 安全组 → 入站规则，**删除**所有 GitHub Actions CIDR 对应的端口 22 规则，恢复到仅允许受信任 IP 访问 SSH。

---

## 附：Workflow 完整 YAML

```yaml
# .github/workflows/deploy-server.yml
name: Deploy OpenClaw + AIVAN Integration

on:
  workflow_dispatch:
    inputs:
      skip_tests:
        description: 'Skip smoke tests (faster)'
        required: false
        default: 'false'
        type: choice
        options: ['false', 'true']
      target_host:
        description: 'Target server IP (default: 113.249.119.30)'
        required: false
        default: '113.249.119.30'

env:
  SERVER_HOST: ${{ inputs.target_host || '113.249.119.30' }}
  SERVER_USER: root
  AGENT_DIR: /opt/giraffe/giraffe-agent
  PLUGIN_DIR: /opt/giraffe/giraffe-agent/integrations/openclaw-aivan-plugin

jobs:
  deploy:
    name: Deploy to ${{ inputs.target_host || '113.249.119.30' }}
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - name: Install sshpass
        run: sudo apt-get install -y sshpass

      - name: '[1/8] Check SSH connectivity'
        env:
          SSHPASS: ${{ secrets.SERVER_SSH_PASSWORD }}
        run: |
          sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20 \
            $SERVER_USER@$SERVER_HOST \
            'echo "✓ SSH connected: $(hostname) | $(date -u)"'

      - name: '[2/8] Compile AIVAN plugin'
        env:
          SSHPASS: ${{ secrets.SERVER_SSH_PASSWORD }}
        run: |
          sshpass -e ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            set -euo pipefail
            cd /opt/giraffe/giraffe-agent/integrations/openclaw-aivan-plugin
            npm install --prefer-offline 2>&1 | tail -5
            npx tsc
            ls dist/
          ENDSSH

      - name: '[3/8] Install plugin into OpenClaw'
        env:
          SSHPASS: ${{ secrets.SERVER_SSH_PASSWORD }}
        run: |
          sshpass -e ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            set -euo pipefail
            openclaw plugins install /opt/giraffe/giraffe-agent/integrations/openclaw-aivan-plugin
            openclaw plugins list | grep -i aivan
          ENDSSH

      - name: '[4/8] Set Gateway environment (AIVAN_BASE_URL)'
        env:
          SSHPASS: ${{ secrets.SERVER_SSH_PASSWORD }}
        run: |
          sshpass -e ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            set -euo pipefail
            mkdir -p $HOME/.config/systemd/user/openclaw-gateway.service.d
            cat > $HOME/.config/systemd/user/openclaw-gateway.service.d/env.conf << 'EOF'
          [Service]
          Environment="AIVAN_BASE_URL=http://localhost:8000"
          Environment="GIRAFFE_API_BASE=http://localhost:8000"
          EOF
            systemctl --user daemon-reload
          ENDSSH

      - name: '[5/8] Enable plugin and restart Gateway'
        env:
          SSHPASS: ${{ secrets.SERVER_SSH_PASSWORD }}
        run: |
          sshpass -e ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            set -euo pipefail
            openclaw config set plugins.entries.openclaw-aivan.enabled true
            openclaw gateway restart
            sleep 5
            openclaw channels status --probe || true
          ENDSSH

      - name: '[6/8] Daemonize AIVAN FastAPI service'
        env:
          SSHPASS: ${{ secrets.SERVER_SSH_PASSWORD }}
        run: |
          sshpass -e ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            set -euo pipefail
            pkill -f "uvicorn api.main:app" 2>/dev/null || true
            sleep 2
            loginctl enable-linger root 2>/dev/null || true
            cat > $HOME/.config/systemd/user/aivan.service << 'EOF'
          [Unit]
          Description=AIVAN Procurement AI Service
          After=network.target

          [Service]
          Type=simple
          WorkingDirectory=/opt/giraffe/giraffe-agent
          Environment="GIRAFFE_DB_MODE=off"
          ExecStart=/opt/giraffe/giraffe-agent/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
          Restart=on-failure
          RestartSec=5

          [Install]
          WantedBy=default.target
          EOF
            systemctl --user daemon-reload
            systemctl --user enable --now aivan.service
            sleep 5
            systemctl --user status aivan.service --no-pager
          ENDSSH

      - name: '[7/8] Health check'
        env:
          SSHPASS: ${{ secrets.SERVER_SSH_PASSWORD }}
        run: |
          sshpass -e ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            set -euo pipefail
            HEALTH=$(curl -sf http://localhost:8000/health)
            echo "$HEALTH"
            echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok'"
            openclaw plugins list | grep -i aivan
            openclaw channels status --probe
          ENDSSH

      - name: '[8/8] Run smoke tests'
        if: inputs.skip_tests != 'true'
        env:
          SSHPASS: ${{ secrets.SERVER_SSH_PASSWORD }}
        run: |
          sshpass -e ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            set -euo pipefail
            cd /opt/giraffe/giraffe-agent
            uv run python scripts/test_openclaw_bside_invoke.py
            uv run python scripts/test_openclaw_mside_invoke.py
          ENDSSH

      - name: Print success criteria
        env:
          SSHPASS: ${{ secrets.SERVER_SSH_PASSWORD }}
        run: |
          sshpass -e ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            echo ""
            echo "╔══════════════════════════════════════════════════╗"
            echo "║          SUCCESS CRITERIA VERIFICATION           ║"
            echo "╚══════════════════════════════════════════════════╝"
            printf '[1] AIVAN health:   '
            curl -sf http://localhost:8000/health \
              | python3 -c "import sys,json; d=json.load(sys.stdin); print('PASS -', d)" 2>/dev/null || echo FAIL
            printf '[2] Plugin enabled: '
            openclaw plugins list 2>/dev/null | grep -iq aivan && echo PASS || echo FAIL
            printf '[3] WeChat channel: '
            openclaw channels status --probe 2>/dev/null | grep -i weixin | head -1 || echo check-manually
            printf '[4] aivan.service:  '
            systemctl --user is-active aivan.service 2>/dev/null || echo FAIL
            printf '[5] Gateway aivan:  '
            journalctl --user -u openclaw-gateway.service -n 50 --no-pager 2>/dev/null \
              | grep -iq aivan && echo 'PASS (in logs)' || echo 'not yet'
          ENDSSH
```

---

*本文档由 Claude Code 生成，对应 commit `82ad9a3` (aivan repo main)*
