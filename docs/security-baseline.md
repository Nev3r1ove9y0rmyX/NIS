# 安全基线检查表（Issue #18 / D-07）

负责人：D；协作：B（应用与数据库）、A（验收核对）。
范围：仅限课程授权的本地实验环境。本表在中期验收前逐项执行并更新状态，
发现的问题全部建 Issue 跟踪（Issue #18 验收标准）。

状态取值：`设计已覆盖`（配置/脚本层面已落实，待环境实测）、`通过`、
`不符合`（附 Issue 编号）、`待现场`（需在 DMZ 环境实测）。

## 1. 口令与凭据

| 编号 | 检查项 | 方式 | 状态 | 证据/备注 |
|---|---|---|---|---|
| SB-01 | 无默认口令：iKuai、Ubuntu、MySQL root、应用账号全部改默认值 | 逐台登录验证 + 尝试默认口令登录失败 | 待现场 | iKuai 首次登录强制改密（ikuai-setup §1.4） |
| SB-02 | 口令强度：所有数据库口令满足 `^[A-Za-z0-9_-]{12,}$` | `deploy/nis.sh verify` + mysql init 主动校验失败 | 设计已覆盖 | init/01 脚本口令不合规即中止建库（已实测拒绝弱口令路径） |
| SB-03 | 无共享口令：7 个 Schema 运行账号 + root + 迁移账号口令互不相同 | 比对 .env（本地抽查，不记录口令本身） | 待现场 | |
| SB-04 | 仓库无明文密钥/口令/Token | `git grep -iE "password|secret|token"` 抽查 + CI 检查 *.pem/.env 不入库 | 通过 | .gitignore 覆盖 .env/*.pem/*.key；本仓库当前无泄漏 |
| SB-05 | JWT 私钥只存在于 iam-service 容器与 D 的加密盘 | compose secrets 挂载清单核对 | 设计已覆盖 | 私钥只挂 iam（compose secrets 段），其余仅公钥 |

## 2. 网络与端口暴露面

| 编号 | 检查项 | 方式 | 状态 | 证据/备注 |
|---|---|---|---|---|
| SB-06 | MySQL 无宿主机端口映射 | `docker compose config` + `ss -tlnp` 核对 | 通过 | compose 未定义 ports；实测仅 data_net 内可达 |
| SB-07 | 8001-8007 服务端口不对宿主/外网暴露 | compose ports 核对 + TC-B05 负向探测 | 设计已覆盖 | 待 TC-B05 现场执行 |
| SB-08 | 外部仅 80/443 可达（映射白名单） | TC-B05 | 待现场 | MAP-01/02 平时关闭 |
| SB-09 | 管理入口（iKuai 界面、SSH）限源 | FW-09/FW-03 + 手工验证 | 待现场 | 仅 10.0.1.104 |
| SB-10 | 无多余服务/端口监听 | srv-dmz-01 `ss -tlnp` 与清单比对 | 待现场 | 预期仅 sshd、docker-proxy(80/443) |

## 3. 数据库安全

| 编号 | 检查项 | 方式 | 状态 | 证据/备注 |
|---|---|---|---|---|
| SB-11 | 按 Schema 最小授权；audit 账号仅 SELECT/INSERT | `SHOW GRANTS` 抽查 + 越权操作实测 | 通过 | 实测 nis_audit_app CREATE 被拒（ERROR 1142） |
| SB-12 | 未授权账号无法连接业务 Schema | 用 recon 账号尝试访问 nis_iam 表应被拒 | 待现场 | 恢复测试实例可复用 |
| SB-13 | root 仅本地/容器内使用，不进应用配置 | grep .env 中服务段无 root 凭据 | 通过 | 服务只注入各自 Schema 账号 |
| SB-14 | 慢查询/审计所需日志可开启且可留存 | nis.cnf 开关 + `SET GLOBAL slow_query_log` | 设计已覆盖 | |

## 4. 应用与中间件（与 B/C 联合）

| 编号 | 检查项 | 方式 | 状态 | 证据/备注 |
|---|---|---|---|---|
| SB-15 | 未认证/越权/无效 Token 均返回 401/403 且写审计 | tests/integration（B，P1） | 待 B 交付 | 对应 TC-B09 |
| SB-16 | 错误响应不含堆栈、SQL、内部地址 | 人工触发错误 + 响应体检查 | 待 B/C 交付 | |
| SB-17 | 调试模式关闭（APP_ENV≠debug） | 验收环境 .env 检查 | 设计已覆盖 | demo.env.example 模板 |
| SB-18 | nginx 不泄露版本号、带基础安全响应头 | `curl -I` 检查 | 通过 | server_tokens off + 三个安全头（已实测） |
| SB-19 | 文件上传限 2MB 且类型受控 | Gateway/nginx 双层限制核对 | 设计已覆盖 | client_max_body_size 2m + GATEWAY_MAX_BODY_BYTES |

## 5. 日志、时间与运维

| 编号 | 检查项 | 方式 | 状态 | 证据/备注 |
|---|---|---|---|---|
| SB-20 | 容器日志有轮转上限 | compose logging 10m×3 | 设计已覆盖 | |
| SB-21 | 日志不含密码/Token/连接串 | grep 容器日志抽样 | 待服务交付后 | B 的服务约束（services/README 第 6 条） |
| SB-22 | 全节点时间同步（偏差<2s） | `date` 比对四终端+主机+iKuai | 待现场 | network-design §8 |
| SB-23 | 系统更新状态记录；不能更新的列入残余风险 | `apt list --upgradable` 快照 | 待现场 | |
| SB-24 | 备份可恢复（异环境实测） | restore.sh + 核对清单 | 通过 | 2026-10-27 实测：见 backup/README 耗时表 |
| SB-25 | 演练前快照/备份、演练后恢复步骤明确 | docs/drill-runbook.md | 设计已覆盖 | |

## 6. 检查执行记录

| 日期 | 执行人 | 范围 | 结论 |
|---|---|---|---|
| 2026-10-27 | D | SB-04/06/11/13/18/24（本地 Docker 环境） | 全部通过 |
| （待现场） | D | 全部"待现场"项 + 与 B/C 联合项 | 待 DMZ 环境搭建后执行 |

## 7. 已发现问题与跟踪

| 问题 | 影响 | Issue | 状态 |
|---|---|---|---|
| bind mount 配置文件在 Docker Desktop 下权限 777 被 mysqld 忽略 | 配置不生效风险 | 已在 #17 修复（cnf 进镜像） | 已修复 |
| mysql 官方入口点子进程运行 init 脚本，docker_process_sql 不可用 | 初始化失败 | 已在 #17 修复（自带 mysql 调用） | 已修复 |
| （新发现的问题在此追加） | | | |
