# deploy

部署与配置目录，主责 D，应用侧配置由 B 提供、A 评审。

## 目录约定

```text
deploy/
  docker-compose.yml       全部服务与 MySQL 的本地/演示编排
  docker-compose.override.yml.example   本地覆盖示例（可选）
  nginx/                   前端与 Gateway 的反向代理配置
  mysql/
    init/                  建库、建账号、授权脚本（不含真实密码）
    conf/                  my.cnf（监听地址、字符集、慢查询）
  backup/                  备份与恢复脚本
  env/                     各环境变量模板（只放占位值）
```

## 端口与暴露面

| 端口 | 服务 | 是否映射到宿主机 | 说明 |
|---:|---|---|---|
| 443/80 | 前端 / Gateway | 是（仅此入口） | 内网与外网都只能访问这里 |
| 8000 | api-gateway | 仅容器网络 | 由反向代理转发 |
| 8001-8007 | 其余服务 | 否 | 只允许 service_net 内访问 |
| 3306 | MySQL | 否 | 只允许服务容器访问 |

网络分层见 [SOA 部署设计](../docs/soa-deployment.md)：
`edge_net`（前端与 Gateway）、`service_net`（internal）、`data_net`（internal）。

## 环境变量

键位以仓库根目录 [.env.example](../.env.example) 为唯一清单。规则：

1. 仓库只提交 `.env.example`，真实 `.env` 由每台机器本地创建；
2. 每个服务只拿自己需要的变量，不用一个万能变量串全部配置；
3. 数据库账号按 Schema 拆分（矩阵见 [数据模型第 12.1 节](../docs/data-model.md)）：
   一个 Schema 一个运行账号，迁移用独立账号且不进运行时容器；`nis_audit` 账号只给
   `SELECT`/`INSERT`，仅对派生索引表 `audit_trace_index` 额外给 `UPDATE`，
   `audit_events` 保持只追加、不授予 `UPDATE`/`DELETE`；
4. JWT 私钥只挂在 IAM 服务上，其余服务只挂公钥；
5. Compose 中不得出现明文密码，统一通过 `env_file` 或环境变量注入。

建库、建号与授权脚本放在 `deploy/mysql/init/`，由 D 维护、B 提供账号与权限清单；
脚本里只写账号名与权限，不写真实口令。

## 启动顺序

1. MySQL 就绪 → 2. 各服务执行自己的迁移 → 3. IAM、Audit 就绪 →
4. 业务服务与 AI 就绪 → 5. Gateway 就绪 → 6. 前端启动。

`depends_on` 不能代替应用级就绪检查；每个服务必须能容忍依赖短暂不可用。

## 验收前必须留证据

- `docker compose ps` 全绿与各服务 `/health/ready` 输出；
- 三域连通与拒绝测试记录（命令 + 结果 + 防火墙命中日志）；
- 一次数据库备份与恢复的校验摘要（不提交备份文件本身）。
