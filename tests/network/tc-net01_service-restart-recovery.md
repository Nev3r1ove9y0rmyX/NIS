# TC-NET01 服务重启自动恢复

| 项 | 内容 |
|---|---|
| 用例编号 | TC-NET01（网络设计新增，待并入追踪矩阵） |
| 关联需求 | soa-deployment §4/§6；Issue #17 验收标准 |
| 目的 | 单个服务崩溃/重启不影响其余服务就绪；整机重启后全栈自动恢复 |
| 执行人 | D |
| 环境 | srv-dmz-01；B 的服务镜像已并入（Issue #17 全量栈） |
| 前置条件 | `docker compose ps` 全部 healthy；记录当前 Git commit |

## 步骤

1. **单服务重启**：模拟 iam-service 崩溃并观察其余服务：

   ```bash
   docker compose exec iam-service kill 1     # 或 docker compose restart iam-service
   for i in 1 2 3 4 5; do
     curl -s -o /dev/null -w "%{http_code}\n" http://10.1.1.20/api/v1/health/live
     sleep 3
   done
   docker compose ps                          # 观察重启策略生效、其余服务仍 healthy
   ```

2. **数据库重启**：`docker compose restart mysql`，验证业务服务短暂报错后
   （`/health/ready` 变 503 再恢复 200），无数据损坏；
3. **整机重启**：`sudo reboot` srv-dmz-01，等待 3 分钟后从内网终端访问
   `http://10.1.1.20/` 并登录，确认 `docker compose ps` 全部恢复 healthy；
4. 全程记录开始/恢复时间戳。

## 期望

- 单服务故障期间其余服务 `/health/live` 保持 200；故障服务按重启策略自动拉起；
- mysql 重启期间依赖服务正确进入未就绪状态，恢复后自动回到 ready；
- 整机重启后无需人工干预全栈可用（`restart: unless-stopped` 生效）；
- 恢复耗时记录进报告（目标：整机 < 3 分钟）。

## 实际结果

（待 Issue #17 全量栈可用后执行）

## 证据

- `evidence/TC-NET01/YYYYMMDD-D-单服务重启恢复.png`（compose ps 前后对比）
- `evidence/TC-NET01/YYYYMMDD-D-整机重启恢复时间线.txt`
