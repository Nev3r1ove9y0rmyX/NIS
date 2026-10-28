# 演练环境与恢复预案（D-09）

负责人：D（演练角色：执行员）；配合：A（演练脚本）、B/C（替补角色）。

## 1. 演练前检查清单（T-1 日）

| # | 项目 | 动作 | 完成 |
|---|---|---|---|
| 1 | 代码版本固定 | `git checkout <commit>` 并记录版本号 | ☐ |
| 2 | 全量备份 | `deploy/backup/backup.sh`，确认 sha256 | ☐ |
| 3 | 配置备份 | .env、deploy/secrets/、iKuai 导出 → D 加密盘 | ☐ |
| 4 | 数据卷快照 | 可选：`docker run --rm -v nis_mysql_data:/data -v $PWD:/bk alpine tar czf /bk/mysql-data.tgz /data` | ☐ |
| 5 | 演示账号可用 | 4 角色账号 + admin 各登录一次（四台终端） | ☐ |
| 6 | 时间同步 | 四终端、srv-dmz-01、iKuai `date` 偏差 <2s | ☐ |
| 7 | 网络标签 | 网线/WAN/LAN/DMZ 贴标；地址表打印随身 | ☐ |
| 8 | 防火墙状态 | TC-B03/04/07 冒烟复测通过；端口映射 MAP-01 开启 | ☐ |
| 9 | 服务健康 | `docker compose -p nis ps` 全 healthy；Gateway ready=200 | ☐ |
| 10 | 日志清点 | `docker logs --since 10m` 抽查无异常；审计可查询 | ☐ |

## 2. 执行员（D）演练流程

依据 [demo-script](demo-script.md) 与 workflow 状态机。演示用指令均为
脱敏的虚构目标（与 A 预先约定）。

1. exec01 登录 → 进入执行工作台；
2. 查看待执行指令（决策员 dmaker01 刚下达的演示指令）；
3. `accept` 接受分配；
4. `start` 开始执行；
5. 填写执行结果 + 上传证据附件；
6. `complete` 提交结果；
7. 与决策员确认结果可见，审计中出现 `assignment.complete` 事件。

## 3. 四种预演场景（与 B/C 排练时逐个过）

| 场景 | 操作 | 预期系统行为 | 演练要点 |
|---|---|---|---|
| 正常 | 上述 1-7 步 | 全链成功，审计完整 | 控制讲解节奏，报出每步状态变化 |
| 失败 | 提交结果时填非法值/漏必填 | 前端明确报错，不落库；可修改后重交 | 展示错误码与提示文案 |
| 重复提交 | 相同 Idempotency-Key 连点两次提交 | 返回原结果，不产生第二条 | 说明幂等键机制 |
| 网络中断 | 执行中拔网线/断 Wi-Fi | 界面进入错误/重试态，不假成功；恢复后可继续 | 演示恢复步骤与日志佐证 |

## 4. 故障恢复步骤

| 故障 | 现象 | 恢复动作 | 预计耗时 |
|---|---|---|---|
| 单服务崩溃 | 某服务 5xx/超时 | `docker compose -p nis restart <svc>`；观察 healthy | <1min |
| 整机失联 | 终端无法访问 10.1.1.20 | 分段 ping：term→10.0.1.1→10.1.1.1→10.1.1.20；重启对应设备/VM | 3-5min |
| 数据损坏 | 业务数据异常 | `deploy/backup/restore.sh <演练前备份>` → `deploy/nis.sh up` → 核对清单 | 5-10min |
| iKuai 配置丢失 | 三域不通 | 控制台导入 configs/ikuai 最近导出或恢复 VM 快照 | 5-10min |
| 端口映射误开 | 外部可达多余端口 | 关闭 MAP 条目 → 复跑 TC-B05 负向 → 记录事件 | <2min |
| JWT 密钥丢失 | 登录全部失败 | 恢复 secrets 备份 → 重启 iam-service（全员需重新登录） | 3min |

紧急停止：演示失控时 `deploy/nis.sh down` 停全栈 + 关闭 MAP-01/02 端口映射，
口头报告 A 后按上表恢复。

## 5. 演练后收尾

1. 导出审计日志与关键截图 → `evidence/`（脱敏）；
2. 再次 `backup.sh`（保留演练后状态）；
3. 关闭 MAP-01/02；环境恢复日常形态；
4. 记录：总耗时、错误次数、补救步骤、改进项（追加到 test-report §5/§6）；
5. 由 C/B 各替补操作一次执行员流程（Issue #32 排练要求）。
