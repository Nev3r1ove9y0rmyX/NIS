# TC-B03 三个网络区域

| 项 | 内容 |
|---|---|
| 用例编号 | TC-B03 |
| 关联需求 | NFR-NET-001（architecture §6、traceability） |
| 目的 | 证明外部、信任内网、DMZ 三域使用不同网段且地址表与实际一致 |
| 执行人 | D |
| 环境 | ikuai-01 + srv-dmz-01 + 四终端 + 外部测试机 |
| 前置条件 | [README 通用前置条件](README.md) |

## 步骤

1. 内网任意终端执行：

   ```bash
   ip addr | grep -E "10\.0\.1\."        # Linux/macOS
   ipconfig | findstr 10.0.1.            # Windows
   ip route | grep default               # 网关应为 10.0.1.1
   ```

2. srv-dmz-01 执行：

   ```bash
   ip -4 addr show | grep 10.1.1.20
   ip route | grep default               # 网关应为 10.1.1.1
   ```

3. iKuai 管理界面「内外网分流」截图 wan1/lan1/dmz1 三个接口地址；
4. 外部测试机执行 `ip addr`，确认地址不在 10.0.1.0/24 与 10.1.1.0/24 内；
5. 对照 [network-design §4 节点清单](../../docs/network-design.md)逐行核对。

## 期望

- 三域地址分别为：现场外部网段 / 10.0.1.0/24 / 10.1.1.0/24，互不重叠；
- 所有静态节点地址、网关、DNS 与设计文档完全一致；
- lan1 DHCP 池为 10.0.1.200-249，dmz1 无 DHCP。

## 实际结果

（待现场执行后填写）

## 证据

- `evidence/TC-B03/YYYYMMDD-D-三域接口与终端地址.png`（iKuai 接口页）
- `evidence/TC-B03/YYYYMMDD-D-终端与服务器地址核对.txt`（命令输出汇总）
