# TC-B05 外网仅能访问映射端口

| 项 | 内容 |
|---|---|
| 用例编号 | TC-B05 |
| 关联需求 | NFR-NET-001；数据流 DF-03/DF-04（network-design §5） |
| 目的 | 外部网络只能访问 10.1.1.20 映射的 80/443，其余端口与内网全部不可达 |
| 执行人 | D |
| 环境 | ext-test-01（接入现场外部网络，与内网/DMZ 不同上游） |
| 前置条件 | [README 通用前置条件](README.md)；已开启 MAP-01 端口映射（验收时段） |

## 步骤（正向）

1. 在 ext-test-01 获取 WAN 侧入口地址：iKuai wan1 IP（记录：______）；
2. 访问映射端口：

   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" http://<wan1-ip>/
   curl -sS -o /dev/null -w "%{http_code}\n" http://<wan1-ip>/api/v1/health/live
   ```

3. 浏览器打开 `http://<wan1-ip>/`，任一角色登录成功并截图。

## 步骤（负向）

4. 探测未映射端口（应全部不可达）：

   ```bash
   for p in 22 8080 3306 8000 8001 8002 8003 8004 8005 8006 8007 3389; do
     nc -z -w3 <wan1-ip> $p && echo "$p OPEN" || echo "$p filtered"
   done
   ```

5. 直接探测内网（应不可达）：`nc -z -w3 10.0.1.20 3306`、`ping -c2 10.0.1.101`；
6. iKuai 日志截图：外部来源命中 FW-90/MAP-01 放行与 FW-91 拒绝的记录。

## 期望

- 步骤 2 通过映射入口返回 200，登录成功；
- 步骤 4 除 80（及开启时的 443）外全部不可达；
- 步骤 5 内网地址不可达；
- 步骤 6 日志与实测一致。

## 实际结果

（待现场执行后填写；注意探测仅针对本团队 wan1 地址，严禁扫描其他地址段）

## 证据

- `evidence/TC-B05/YYYYMMDD-D-外部访问映射端口成功.png`
- `evidence/TC-B05/YYYYMMDD-D-外部未映射端口全拒.txt`
- `evidence/TC-B05/YYYYMMDD-D-防火墙外部命中日志.png`
