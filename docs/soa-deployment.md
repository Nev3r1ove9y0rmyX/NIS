# SOA 部署设计

版本：1.0（已冻结，2026-10-27）

## 1. 部署目标

- 单台基础设施电脑可以运行完整系统；
- 四台终端通过统一 Gateway 同时使用；
- 只有 Gateway 映射到外部/内网可访问接口；
- 内部服务与 MySQL 不直接暴露；
- 可通过 Docker Compose 一条命令启动和停止。

## 2. Docker 网络

```text
edge_net
  frontend
  api-gateway

service_net (internal)
  api-gateway
  iam-service
  recon-service
  analysis-service
  decision-service
  execution-service
  ai-service
  audit-service

data_net (internal)
  iam/recon/analysis/decision/execution/ai/audit services
  mysql
```

- `edge_net` 接收来自 DMZ Gateway 主机端口的请求。
- `service_net` 标记为 internal，承载服务间 REST。
- `data_net` 标记为 internal，承载服务到 MySQL。
- 前端和 Gateway 不直接连接数据库。
- MySQL 不配置宿主机公开端口；本地维护通过受控临时命令或指定管理路径进行。

## 3. 服务发现

P0 阶段使用 Docker Compose 服务名作为内部 DNS：

```text
http://iam-service:8001
http://recon-service:8002
http://analysis-service:8003
http://decision-service:8004
http://execution-service:8005
http://ai-service:8006
http://audit-service:8007
```

不部署 Consul、Eureka 或 Kubernetes。若部署方式变化，再新增 ADR。

## 4. 启动依赖

1. MySQL 启动并通过健康检查；
2. 各服务执行自身 Schema 迁移；
3. IAM 和 Audit 就绪；
4. 业务服务和 AI 服务就绪；
5. Gateway 就绪；
6. 前端启动。

Compose 的 `depends_on` 不能代替应用级就绪检查。每个服务必须容忍依赖短暂不可用并快速失败。

## 5. 配置与密钥

- 仓库只提交 `.env.example`；
- MySQL root 密码、各 Schema 密码、JWT 私钥、服务令牌和 AI 密钥不得进入 Git；
- 每个服务配置自己的数据库 DSN 和下游地址；
- 开发、测试和验收环境使用不同配置；
- 日志中不得打印连接串密码或 Token。

## 6. 健康检查

- `/health/live`：进程能够响应，不检查全部下游；
- `/health/ready`：本服务数据库和必需依赖满足接收请求条件；
- Gateway 就绪状态列出关键依赖摘要，但不泄露地址和凭据；
- D 保存验收时各服务健康状态截图或输出。

## 7. 外部网络映射

- 生产式演示优先只映射 HTTPS；条件有限时可映射批准的 HTTP 端口。
- 外网和信任内网只能访问 Gateway/前端地址。
- 8001 至 8007 及 3306 不做 iKuai 端口映射。
- DMZ 到信任内网全部拒绝。

## 8. 最小资源建议

- 基础设施主机建议至少 16 GB 内存；
- 服务容器使用统一 Python 基础镜像，减少重复镜像占用；
- 开发期可按当前任务只启动所需服务；
- 验收前必须在完整 Compose 下执行四终端并发和故障恢复测试。
