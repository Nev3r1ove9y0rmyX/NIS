# TC-B04 内网访问外网与 DMZ

| 项 | 内容 |
|---|---|
| 用例编号 | TC-B04 |
| 关联需求 | NFR-NET-001；数据流 DF-01/DF-02/DF-06（network-design §5） |
| 目的 | 内网终端可访问外网与 DMZ 公开服务；内网到 DMZ 未授权端口被拒绝 |
| 执行人 | D |
| 环境 | term-a（10.0.1.101）作为内网代表终端 |
| 前置条件 | [README 通用前置条件](README.md)；系统已启动 |

## 步骤（正向）

1. 访问 DMZ Web 入口：

   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" http://10.1.1.20/
   curl -sS -o /dev/null -w "%{http_code}\n" http://10.1.1.20/api/v1/health/live
   ```

2. 浏览器打开 `http://10.1.1.20/` 完成一次登录，截图（TC-B04 与 TC-B08 联合取证）；
3. 访问外网（更新/依赖能力验证）：

   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" https://example.com/
   ```

   > 仅访问公共只读站点用于连通性证明，不做任何扫描。

4. srv-dmz-01 验证 DNS（DF-06）：`dig +short example.com @10.1.1.1`。

## 步骤（负向）

5. 内网终端探测 DMZ 未授权端口（应全部失败）：

   ```bash
   # Windows PowerShell
   10.1.1.20,22,3306,8000,8001,8007 | ForEach-Object -Begin {$i=0} -Process { if($i%2 -eq 0){$h=$_}else{ tnc $h -Port $_ -InformationLevel Quiet }; $i++ }

   # Linux/macOS
   for p in 22 3306 8000 8001 8002 8003 8004 8005 8006 8007; do
     nc -z -w2 10.1.1.20 $p && echo "$p OPEN" || echo "$p filtered"
   done
   ```

## 期望

- 步骤 1 两个请求均返回 2xx/3xx（健康检查 200）；
- 步骤 3 返回 200；
- 步骤 4 返回解析结果；
- 步骤 5 中 22/3306/8000-8007 全部不可达（除 FW-03 允许的 term-d→22 场景外）；
- iKuai 防火墙日志出现 FW-02 放行与 FW-04 拒绝记录（对应 TC-NET02）。

## 实际结果

（待现场执行后填写）

## 证据

- `evidence/TC-B04/YYYYMMDD-D-内网访问DMZ-Web与API.png`
- `evidence/TC-B04/YYYYMMDD-D-内网端口探测全拒.txt`
- `evidence/TC-B04/YYYYMMDD-D-内网访问外网.png`
