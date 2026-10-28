# 网络测试用例（D 负责）

依据：[docs/network-design.md](../../docs/network-design.md)、iKuai 配置
[deploy/network/ikuai-setup.md](../../deploy/network/ikuai-setup.md)。

## 用例索引

| 用例 | 目的 | 状态 |
|---|---|---|
| [TC-B03](tc-b03_three-zone-segmentation.md) | 三域网段与实际配置一致 | 待执行 |
| [TC-B04](tc-b04_lan-to-dmz-and-internet.md) | 内网可访问外网与 DMZ 服务 | 待执行 |
| [TC-B05](tc-b05_external-to-dmz-only.md) | 外部仅能访问映射端口 | 待执行 |
| [TC-B07](tc-b07_dmz-to-lan-denied.md) | DMZ 到内网全部拒绝 | 待执行 |
| [TC-NET01](tc-net01_service-restart-recovery.md) | 服务重启自动恢复 | 待执行 |
| [TC-NET02](tc-net02_firewall-log-evidence.md) | 防火墙日志与结果一致 | 待执行 |

TC-B03/04/05/07 编号沿用[需求追踪矩阵](../../docs/traceability.md)；
TC-NET01/02 为网络设计新增，待 A 并入矩阵。

## 状态与证据约定

- 状态取值：`待执行` / `通过` / `失败` / `阻塞`；
- 每次执行更新用例文件"实际结果"小节，并在
  `evidence/<用例编号>/YYYYMMDD-D-<内容>.png|txt` 保存脱敏证据；
- 失败不覆盖历史：保留旧记录，追加"复测"小节；
- Windows 终端用 `Test-NetConnection`（简写 `tnc`），Linux/macOS 用 `nc`/`curl`，
  证据截图中需可见源主机与命令。

## 通用前置条件

1. [ikuai-setup.md §6](../../deploy/network/ikuai-setup.md) 配置核对表全部打勾；
2. 四台终端、srv-dmz-01、外部测试机地址与设计文档 §4 一致；
3. 系统已部署（`deploy/nis.sh up` 后 `docker compose ps` 全部 healthy）；
4. 各节点时间偏差 < 2 秒（`date` 比对）。
