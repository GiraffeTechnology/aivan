# AIVAN / OpenClaw 部署隔离 SOP（Stage 7）

状态：**生产部署已隔离，当前仓库不提供可执行部署动作。**

旧版工作流包含过期主机、口令式 SSH、关闭主机校验、原地改写服务和
直接重启进程等不可接受行为，已由 Stage 7 替换为只记录候选版本与授权
编号的无副作用工作流。当前 `.github/workflows/deploy-server.yml`：

- 不读取任何 Secret；
- 不安装 `sshpass`；
- 不建立 SSH、HTTP、SMTP 或 IM 连接；
- 不上传文件、不运行迁移、不重启进程；
- 不修改 OpenClaw、AIVAN、MySQL、DNS/CDN 或反向代理；
- 不接触 AIVAN 服务器的 `443`/`8443` 端口；
- 不向中国大陆以外 IP 发起流量。

## 不可绕过的基础设施约束

1. AIVAN 生产主机位于 CTYun；目标身份必须由授权运维清单解析，不接受
   自由输入 IP。
2. AIVAN 服务器 `443`/`8443` 已由 SSH/MAIL 使用，myAIVAN/AIVAN 不得
   修改、监听、复用、转发或重启相关服务。
3. CTYun 访问中国大陆以外 IP 必须经 `abcdyi-sin` 新加坡桥接；部署程序
   不得自行直连境外依赖。
4. 密码、私钥、Access Key、Secret Key 与 Token 只能由授权 Secret Store
   注入，禁止进入仓库、Action 输入、日志或证据文件。
5. 未取得明确的逐次生产授权时，禁止部署、外发、迁移、数据库写入、
   DNS/CDN 修改和服务重启。

## Stage 7F 才可恢复部署自动化

恢复部署能力必须另开 PR，并同时满足：

- 候选提交以完整 40 位 SHA 冻结，依赖锁与构建产物有 SHA-256；
- GitHub Environment 已启用指定审批人、分支限制与 Secret 隔离；
- 目标主机指纹、非 root 最小权限账号及固定目录均已核验；
- 迁移计划、备份、恢复演练和回滚命令经双人复核；
- 端口占用预检明确证明 `443`/`8443` 零变更；
- 境外依赖流量的 `abcdyi-sin` 路由证据可追溯；
- 部署前后健康、容量、日志、指标和告警检查齐备；
- Email/LINE/微信引导中继等真实通道仅在单独授权范围内测试；
- 连续五轮 production acceptance 全部通过并由项目主管签署。

## 当前可执行动作

`Deployment quarantine record (no deployment)` 仅校验候选 SHA 与授权引用，
并在 GitHub Step Summary 记录“未部署、未读 Secret、未连远端”的事实。
其成功不代表部署成功，也不能作为 production acceptance 证据。
