# 系统与网络测试报告（骨架，持续更新）

负责人：D（D-08）；A 汇总中期验收材料时引用本报告。
诚实性约定：**未执行的测试一律标注"待执行/待现场"，不得把设计预期写成实测结果**。
每条用例的命令、期望与证据路径见 [tests/network/](../tests/network/README.md)。

## 1. 测试环境

| 项 | 值 |
|---|---|
| 基础设施主机 | D 的电脑（Windows + Docker Desktop 29.4 / Compose v5.1.2，本地验证环境） |
| 目标部署环境 | srv-dmz-01 Ubuntu VM（10.1.1.20，按 [network-design](network-design.md) 搭建） |
| 代码版本 | <Git commit>（现场填写） |
| 网络三域 | 外部网段 / LAN 10.0.1.0/24 / DMZ 10.1.1.0/24（iKuai，待现场搭建） |
| 测试账号 | recon01/analyst01/dmaker01/exec01 + admin（只写用户名） |

## 2. 测试范围与分工

- 网络与安全测试：D（本报告主体）；
- 接口/契约测试：B（tests/integration、tests/contract）；
- 端到端与多用户冲突：A 组织全员（tests/e2e）；
- 前端交互与错误反馈：C。

## 3. 用例状态总览

| 用例 | 名称 | 关联需求 | 状态 | 证据 |
|---|---|---|---|---|
| TC-B03 | 三域网段与网关 | NFR-NET-001 | 待现场 | - |
| TC-B04 | 内网访问外网与 DMZ | NFR-NET-001 | 待现场 | - |
| TC-B05 | 外部仅访问映射端口 | NFR-NET-001/NFR-SEC | 待现场 | - |
| TC-B07 | DMZ 禁止访问内网 | NFR-SEC-002 | 待现场 | - |
| TC-NET01 | 服务重启自动恢复 | soa-deployment §4/6 | 待服务交付 | - |
| TC-NET02 | 防火墙日志一致性 | network-design §6 | 待现场 | - |
| TC-B01/02 | 数据库落库/日志完整性 | FR-* | 待服务交付（B） | - |
| TC-B08~15 | 认证/RBAC/OODA/多用户 | FR-AUTH/ORG | 待服务交付（B/C/A） | - |
| SB-* | 安全基线 25 项 | 见 [security-baseline](security-baseline.md) | 6 项通过，其余待现场/待交付 | security-baseline §6 |

## 4. 已完成的本地验证（2026-10-27，D 的本机 Docker）

以下为**本地环境实测**，非 DMZ 验收环境结果：

1. **MySQL 初始化（对应 #17 验收）**：`deploy/nis.sh db` 一次启动成功；
   7 个 Schema、7 运行账号、7 迁移账号全部建成；`nis_audit_app` 执行
   `CREATE TABLE` 被拒（ERROR 1142，验证只追加授权）；容器 healthy；
   无 world-writable 配置告警。
2. **边缘代理路由（对应 #17 验收）**：以假上游容器实测——`/healthz` 返回
   200 "ok"、`/` 转发前端 200、`/api/v1/*` 转发 Gateway、安全响应头齐全
   （X-Content-Type-Options/X-Frame-Options/Referrer-Policy）。
   过程中发现并修复：多 server 块导致默认 server 吞请求的 404 缺陷。
3. **备份恢复（对应 #18 验收，TC 类比 SB-24）**：备份 832KB 含全部
   Schema/账号/授权；恢复到隔离容器耗时 2-3s；users 表 2 行 HEX 级一致；
   14 个账号与授权（含 audit 仅 SELECT/INSERT）恢复后逐项一致；
   FLUSH PRIVILEGES 后授权生效。
4. **SSRF 加固（配合仓库安全扫描）**：seed 脚本新增目标校验，
   file://、带凭据 URL、关闭开关后的回环/私网目标均被拒绝（已实测）。

已知环境差异：本机 Docker Desktop 的容器名 DNS 解析异常（用户态网络怪癖），
故边缘路由测试以 `--add-host` 显式注入上游地址完成；DMZ Linux 主机上
compose 服务名解析正常，不影响部署方案。

## 5. 缺陷与修复记录

| 编号 | 现象 | 根因 | 修复 | 复测 |
|---|---|---|---|---|
| D-BUG-01 | mysql 配置 nis.cnf 未生效（World-writable 告警） | Docker Desktop bind mount 权限 777 被 mysqld 拒绝 | cnf 构建进镜像（#17） | 通过，告警消失 |
| D-BUG-02 | init 脚本报 docker_process_sql not found | 官方入口点以子进程执行 .sh | 自带 mysql 客户端调用（#17） | 通过，建库完整 |
| D-BUG-03 | nginx 任意 Host 请求返回 404 | healthz 独立 server 块成为默认 server | 合并为单一 default_server 块（#17） | 通过，三条路径正确 |
| D-BUG-04 | 恢复后账号存在但授权不生效 | mysql.* 表直改后未刷新权限缓存 | 恢复流程末尾 FLUSH PRIVILEGES（#18） | 通过 |
| D-BUG-05 | 恢复核对 UNION 查询整体失败 | 引用未迁移表 | 改为逐表独立统计（#18） | 通过 |

## 6. 未解决风险与待办

1. **三域网络与防火墙策略尚未实际搭建**（依赖现场设备）：TC-B03/04/05/07、
   TC-NET02、SB-01/03/07~10/12/22/23 全部待现场执行；
2. 8 个服务镜像未交付（依赖 B 的 Issue #7~#11）：TC-NET01、SB-15/16/21 待交付后执行；
3. 前端未交付（C 的 Issue #12~#14）：四终端并发登录（TC-B08 联测）待交付；
4. 本地 Windows 与 DMZ Ubuntu 的 Docker 行为差异（DNS、文件权限）已记录，
   部署演练时需按 DMZ 环境复跑一遍 compose 验证。

## 7. 中期验收结论

（全部 P0 用例执行后填写：通过/有条件通过/不通过 + 理由）
