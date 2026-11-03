# 现场部署与演示操作单（A 的电脑：2 台虚拟机 + Windows 宿主）

更新：2026-11-03 · 实测环境：Ubuntu 24.04 + Docker Compose + iKuai 3.7.26 + MySQL 8.4

本单按"开机到能演示"的顺序排列，每一步都有可验证的输出。所有命令均在对应机器上执行。

## 一、机器与地址（实测值，现场按 `ipconfig` / `ip -br a` 核对）

| 角色 | 机器 | 地址 | 说明 |
|---|---|---|---|
| 边界/防火墙 | iKuai VM | LAN1 `10.252.150.10`、LAN2 `192.168.58.2`、WAN1 `192.168.146.10` | 三块虚拟网卡 |
| DMZ 应用 | Ubuntu VM | `192.168.58.20` | Docker Compose：11 个容器 |
| 外部测试机 | Windows 宿主 VMnet8 | `192.168.146.1` | 访问 iKuai WAN 口 |
| 内网终端 | Windows 宿主 WLAN / B、C、D 三台 | 热点 DHCP（`10.252.150.x`） | 浏览器访问 `http://192.168.58.20` |
| 热点 | 手机 | 网关 `10.252.150.129` | 只提供 L2 与 DHCP |

虚拟网络：VMnet0 桥接无线（内网）、VMnet1 仅主机 `192.168.58.0/24`（DMZ）、VMnet8 NAT `192.168.146.0/24`（外网）。

## 二、启动顺序（冷启动约 5 分钟）

```text
1. 手机开热点
2. Windows 连热点（确认拿到 10.252.150.x）
3. 启动 iKuai VM —— 必须先起，它是 DMZ 主机的网关
4. 启动 Ubuntu VM
5. （可选，AI 演示需要）启动 Windows 上的 Ollama
6. 验证 11 个容器 healthy，必要时 ./deploy/nis.sh up
7. 三端验证：Ubuntu 本机 / 内网终端 / 外网口
```

### 2.1 Ubuntu 上的检查（按顺序）

```bash
cd ~/NIS

# 1) 网络
ip -br a | grep 192.168.58          # 期望 192.168.58.20/24
ping -c1 192.168.58.2               # iKuai LAN2 必须通

# 2) 容器是否已自动起来（Docker 已开机自启 + 容器 unless-stopped）
docker compose -p nis ps            # 期望 11 个 healthy

# 3) 没起来或数量不对时再手动拉起
./deploy/nis.sh up

# 4) 若刚重建过 api-gateway（或接口 502）
./deploy/nis.sh restart edge-proxy
```

### 2.2 三端验证

```bash
# Ubuntu 本机
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/
curl -s http://127.0.0.1/health/live

# Windows（内网）
curl.exe -I http://192.168.58.20/

# Windows（外网口）
curl.exe -I http://192.168.146.10/
```

### 2.3 开机自启的真实行为

| 组件 | 行为 |
|---|---|
| Docker | `systemctl is-enabled docker` = enabled，随 VM 启动 |
| 11 个容器 | `restart: unless-stopped`，随 Docker 自动恢复 |
| 例外 | 上次若执行过 `./deploy/nis.sh down`（手动停止），则不会自动起，需要 `up` |
| nginx 上游 | `edge-proxy` 的 `depends_on` 会等 gateway/frontend healthy 后再启动，整机冷启动不会缓存错 IP；只有"运行中重建 gateway"才需要 `restart edge-proxy` |

### 2.4 关闭顺序（避免 MySQL 强杀）

```bash
cd ~/NIS
./deploy/nis.sh down     # 先优雅停止容器
# 再关闭 Ubuntu VM，最后关闭 iKuai VM
```

期望 11 个容器：mysql、iam、audit、recon、analysis、decision、execution、ai、api-gateway、frontend、edge-proxy。

## 三、网络配置核对（iKuai Web 后台）

| 位置 | 配置 |
|---|---|
| 网络设置 → 内外网设置 | LAN1 `10.252.150.10/24`（不启用 DHCP）、LAN2 `192.168.58.2/24`、WAN1 静态 `192.168.146.10/24` 网关 `192.168.146.2` |
| 网络设置 → 端口映射 | WAN1 TCP 80 → `192.168.58.20:80`（**只映射 80**） |
| 安全设置 → ACL 规则 | ① 阻断 **TCP** `192.168.58.0/24` → `10.252.150.0/24`<br>② 阻断 **UDP** 同上<br>③ 允许 `10.252.150.0/24` → `192.168.58.0/24`（任意协议）<br>④ 允许 `192.168.58.0/24` → 任意（DMZ 出网） |

ACL 的「连接方向匹配」必须选 **原始方向**。

**阻断规则必须拆成 TCP 与 UDP 两条、不要用「任意协议」**：ICMP 没有连接状态，用任意协议阻断时会把 ping 的回程响应一起拦掉，表现为内网 ping 不通 DMZ、网页转圈。拆开后：内网 → DMZ 的 ping 正常；DMZ → 内网**服务（TCP/UDP）**不可达，这正是验收要求的「无法访问内网主机服务」。

## 四、四终端接入

B/C/D 三台 Windows 笔记本（管理员 PowerShell，各执行一次）：

```powershell
route add 192.168.58.0 mask 255.255.255.0 10.252.150.10 -p
curl.exe -sI http://192.168.58.20/          # 期望 200
```

**判定路由是否真的生效**：在终端执行 `tracert -h 3 192.168.58.20`，第一跳必须是 `10.252.150.10`（iKuai）；若第一跳是热点网关（如 `10.252.150.129`），说明路由没加上。

A 的 Windows 宿主**不要**加这条路由：它自带 VMnet1 网卡（`192.168.58.1`）直连 DMZ；如果误加，会把访问改道到 iKuai，反而打不开（用 `route delete 192.168.58.0 mask 255.255.255.0` 删除，再 `route add 192.168.58.0 mask 255.255.255.0 192.168.58.1` 恢复）。
A 的手机只能当热点，无法加路由，因此**不承担终端角色**（报告里如实说明）。

## 五、数据初始化（已执行，仅重建环境时需要）

```bash
cd ~/NIS
# 1) 迁移（容器内执行，不需要暴露 3306）
docker run --rm --network nis_data_net --env-file .env \
  -v "$PWD":/repo -w /repo --entrypoint python \
  -e MYSQL_HOST=mysql -e IAM_DB_MIGRATE_PASSWORD="$(grep '^IAM_MIGRATE_PASSWORD=' .env | cut -d= -f2-)" \
  nis-iam-service scripts/migrate_all.py --verify      # 其余服务按需传各自 MIGRATE 口令

# 2) 初始数据（组织/角色/权限/账号）
docker run --rm --network nis_data_net --env-file .env \
  -v "$PWD":/repo -w /repo --entrypoint python \
  -e NIS_ADMIN_PASSWORD=****** -e NIS_DEMO_PASSWORD=****** \
  nis-iam-service scripts/seed_data.py
```

迁移成功标志：7 个 Schema 各打印表清单（iam 7 张、audit 3 张、recon 4 张、analysis 4 张、decision 4 张、execution 3 张、ai 3 张）。

## 六、演示顺序（15 分钟）

| 时长 | 内容 | 操作 | 预期 |
|---|---|---|---|
| 1′ | 三域可见 | `ipconfig`（终端）/`ip -br a`（Ubuntu）/iKuai 状态页 | 三个不同网段 |
| 1′ | 内网→外网 | 浏览器百度 | 200 |
| 1′ | 内网→DMZ | `curl.exe -I http://192.168.58.20/` | 200 |
| 1′ | **外网→DMZ** | Windows：`curl.exe -I http://192.168.146.10/`；再试 `:3306` | 首页 200、3306 失败 |
| 1′ | **DMZ→内网** | Ubuntu：`ping -c2 10.252.150.129` | 100% 丢包 |
| 4′ | OODA 闭环 | C 侦察 → B 分析 → D 决策 → A 执行 → D 回看 | 聚合状态 `completed` |
| 1′ | 权限 | 侦察员访问分析页 | 403 |
| 1′ | 审计 | admin 打开审计页 / `GET /audit-events` | 有事件、可按 request_id 还原 |
| 2′ | 扩展演示 | 优先级标红、限时角色、在线状态、IP 绑定、任务转交 | 对应接口/页面 |
| 2′ | 兜底 | 脚本：`python3 scripts/seed_demo_data.py --with-loop` | 打印四段状态 |

演示账号：`admin`、`recon01`、`analyst01`、`dmaker01`、`exec01`（口令见现场记录，不入库）。

## 七、一键自检

```bash
# Ubuntu 上
cd ~/NIS
docker compose -p nis ps | grep -c healthy          # 期望 11
curl -s --noproxy '*' -o /dev/null -w "%{http_code}\n" http://127.0.0.1/
curl -s --noproxy '*' -o /dev/null -w "%{http_code}\n" http://127.0.0.1/health/live
ping -c1 -W1 10.252.150.129 >/dev/null && echo "ACL 失效！" || echo "DMZ→内网 已阻断"
# Windows 上
curl.exe -s --noproxy '*' -o NUL -w "%{http_code}\n" http://192.168.146.10/
curl.exe -s --noproxy '*' -o NUL -w "%{http_code}\n" http://192.168.58.20/
```

## 七之补充、AI 接真实模型（Ollama）

现场若要用本地大模型演示：

```bash
# 1) 宿主机：Ollama 监听所有网卡并确认模型
setx OLLAMA_HOST 0.0.0.0:11434      # 重启 Ollama 后生效
ollama list                          # 需要 gemma3:4b（约 3.4 GB，60 秒内可出结果）

# 2) DMZ 上确认可达
curl -s http://192.168.58.1:11434/api/tags | head -c 80

# 3) .env 配置
AI_ENABLED=true
AI_PROVIDER=ollama
AI_BASE_URL=http://192.168.58.1:11434
AI_MODEL=gemma3:4b
AI_TIMEOUT_SECONDS=90
HTTP_TOTAL_TIMEOUT=120

# 4) 应用（compose 已把 ai-service 加入 edge_net，nginx 已放宽到 300s）
./deploy/nis.sh up
```

| 注意 | 说明 |
|---|---|
| `gemma4:26b` 太慢 | 17 GB，8 GB 显存装不下，单次约 2 分钟；演示请用 `gemma3:4b` |
| 回退机制 | 模型超时/报错自动回退规则模板（`model_name` 带 `(fallback)`），演示不中断 |
| 降级演示 | `.env` 设 `AI_ENABLED=false` 重启 ai-service，接口返回 503 |

## 八、八个已踩过的坑（现场直接对照）

| 现象 | 原因 | 处理 |
|---|---|---|
| `env: "bash\r"` 无此文件 | Windows 传文件带 CRLF | `dos2unix deploy/nis.sh` 或整个仓库转换 |
| `unknown flag: --profile` | compose v2 要求 `--profile` 在子命令前 | `compose --profile app up -d` |
| `failed to read dockerfile` | `frontend/Dockerfile` 缺失 | 已补（多阶段 node→nginx） |
| `COPY services/... not found` | compose 构建上下文写成服务目录 | 改为 `context: ..` + `dockerfile: services/x/Dockerfile` |
| Docker Hub 超时 | 无镜像加速 | `/etc/docker/daemon.json` 配 registry-mirrors |
| 登录 500（`no such table user_sessions`） | 新增表未进 alembic | 已补迁移 `b7c1e5a93d24` |
| 审计查询 502 / 写入 422 | audit 缺 `IAM_SERVICE_URL`；nginx 32 位 request_id | 已补 env；request_id 放宽到 8–64 位 |
| AI 建议 502，错误里 target 是 `127.0.0.1:8001` | ai-service 缺 `IAM_SERVICE_URL` | 已补 `http://iam-service:8001` |
| AI 建议 0 秒回退模板 | ai-service 在 internal 网络，到不了宿主机 Ollama | 已把 ai-service 加入 `edge_net` |
| 重建 gateway 后接口全部 502 | nginx 启动时缓存旧上游 IP，容器重建后 IP 变化 | `docker compose -p nis restart edge-proxy` |

另有两处是演示前必须确认的：

1. execution-service 必须有 `DECISION_SERVICE_URL`，否则执行完成后指令总体状态停在 `issued`；
2. 网关必须**沿用**反向代理的 `X-Forwarded-For`，否则所有终端的源 IP 都会被记成边缘代理地址，IP 绑定和审计失真。

## 九、停止与重启

```bash
./deploy/nis.sh down      # 停止（保留数据卷）
./deploy/nis.sh up        # 启动
./deploy/nis.sh nuke      # 危险：停止并删除数据卷（重装才用）
docker compose -p nis logs -f iam-service   # 看日志
```
