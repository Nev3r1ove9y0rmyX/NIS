# deploy

部署与配置目录，主责 D，应用侧配置由 B 提供、A 评审。

## 目录约定

```text
deploy/
  docker-compose.yml       全部服务与 MySQL 的本地/演示编排
  docker-compose.override.yml.example   本地覆盖示例（可选）
  nis.sh                   统一部署助手（up/db/down/nuke/gen-keys/verify/透传）
  nginx/
    conf.d/nis.conf        前端与 Gateway 的反向代理配置（80，443 预留）
  mysql/
    init/                  建库、建账号、授权脚本（不含真实密码）
    conf/nis.cnf           my.cnf（字符集、监听说明、慢查询开关）
  env/
    demo.env.example       DMZ 验收环境实例模板（差异键子集）
  network/
    ikuai-setup.md         iKuai 三域网络配置步骤（Issue #16）
  backup/                  备份与恢复脚本（Issue #18）
  secrets/                 JWT 密钥（gen-keys 生成，*.pem 被 gitignore）
```

## 端口与暴露面

| 端口 | 服务 | 是否映射到宿主机 | 说明 |
|---:|---|---|---|
| 443/80 | edge-proxy（nginx） | 是（仅此入口） | 内网与外网都只能访问这里 |
| 8000 | api-gateway | 仅容器网络 | 由反向代理转发 |
| 8001-8007 | 其余服务 | 否 | 只允许 service_net 内访问 |
| 3306 | MySQL | 否 | 只允许服务容器访问 |

网络分层见 [SOA 部署设计](../docs/soa-deployment.md)：
`edge_net`（前端、Gateway 与边缘代理）、`service_net`（internal）、
`data_net`（internal）。

## 快速部署（新主机，Issue #17 验收路径）

前置：Ubuntu 22.04+，已装 Docker 与 compose 插件；主机地址/网关按
[network-design §4](../docs/network-design.md)（srv-dmz-01 = 10.1.1.20）。

```bash
# 0) 获取代码并固定版本（记录进验收报告）
git clone <repo> && cd NIS && git checkout <tag-or-commit>

# 1) 配置环境变量（所有口令满足 ^[A-Za-z0-9_-]{12,}$，否则库初始化会主动失败）
cp .env.example .env && $EDITOR .env        # 按 deploy/env/demo.env.example 调整

# 2) 生成 JWT 密钥对（本机保存，不入 Git）+ 配置自检
deploy/nis.sh gen-keys
deploy/nis.sh verify

# 3) 启动
deploy/nis.sh up          # 全栈（--profile app）；开发期可 deploy/nis.sh db 只起 mysql

# 4) 健康检查（全部 healthy 才算成功）
docker compose -p nis ps
curl -s http://127.0.0.1/api/v1/health/live      # 经 nginx → Gateway

# 5) 首次数据：迁移 + 种子（等 B 的 Issue #7 提供 migrate 入口与种子脚本）
#    迁移账号口令只在运维会话提供，不写入 .env 运行段
```

说明：

- 服务镜像未交付前 `up` 会在构建 8 个服务时报错；此时 `deploy/nis.sh db`
  即可让 mysql（含全部 Schema 与账号）就绪供 B/C 开发；
- `AI_BASE_URL` 在容器内默认 `127.0.0.1` 指向容器自身，宿主机模型需改为
  `http://host.docker.internal:11434`（Docker Desktop）或 DMZ 主机地址；
  AI 不可用时按契约降级，不阻断人工流程；
- MySQL 首次启动时 `mysql/init/01-databases-and-accounts.sh` 自动执行：
  7 个 Schema、7 个运行账号（audit 仅 SELECT/INSERT）、7 个迁移账号。

## 更新与回滚

```bash
# 更新到指定版本
git fetch --tags && git checkout <new-commit>
deploy/nis.sh up                       # 重建变更过的镜像
docker compose -p nis ps               # 全部 healthy 后验证一条登录链路

# 回滚
git checkout <last-known-good-commit>
deploy/nis.sh up
# 数据层回滚：用最近一次备份恢复，见 backup/（恢复前先备份当前库）
```

## 环境变量

键位以仓库根目录 [.env.example](../.env.example) 为唯一清单。规则：

1. 仓库只提交 `.env.example`，真实 `.env` 由每台机器本地创建；
2. 每个服务只拿自己需要的变量：compose 对每个服务**显式列出**所需键，
   不整包加载 .env；
3. 数据库账号按 Schema 拆分（矩阵见 [数据模型第 12.1 节](../docs/data-model.md)）：
   一个 Schema 一个运行账号；迁移用独立账号（`nis_<schema>_migrate`）且不进
   运行时容器；`nis_audit` 账号只给 `SELECT`/`INSERT`，不授予
   `UPDATE`/`DELETE`；
4. JWT 私钥只挂在 IAM 服务上（`deploy/secrets/`，`gen-keys` 生成），
   其余服务只挂公钥；
5. Compose 中不得出现明文密码，统一通过环境变量注入；缺失关键变量时
   compose 启动即失败并提示键名。

建库、建号与授权脚本放在 `deploy/mysql/init/`，由 D 维护、B 提供账号与权限清单；
脚本里只写账号名与权限，不写真实口令。

## 启动顺序

1. MySQL 就绪 → 2. 各服务执行自己的迁移 → 3. IAM、Audit 就绪 →
4. 业务服务与 AI 就绪 → 5. Gateway 就绪 → 6. 前端启动。

`depends_on` 不能代替应用级就绪检查；每个服务必须能容忍依赖短暂不可用。
容器 `restart: unless-stopped` + 健康检查，重启恢复验证见
[TC-NET01](../tests/network/tc-net01_service-restart-recovery.md)。

## 验收前必须留证据

- `docker compose ps` 全绿与各服务 `/health/ready` 输出；
- 三域连通与拒绝测试记录（命令 + 结果 + 防火墙命中日志）；
- 一次数据库备份与恢复的校验摘要（不提交备份文件本身）。
