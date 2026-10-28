# 备份与恢复（Issue #18）

负责人：D；协作：B。
目标：数据库可备份、可在另一环境恢复、恢复结果可核对；配置与证据有明确备份范围。

## 备份范围与位置

| 对象 | 方式 | 位置 | 保留 |
|---|---|---|---|
| MySQL 全实例（7 个 Schema + 账号授权 + 系统库） | `backup.sh`（mysqldump --single-transaction，gzip） | 本机 `deploy/backup/backups/`（gitignore） | 演示前 1 份 + 每次变更后 1 份；验收后归档 1 份至 D 的加密盘，保留至课程结束 |
| 配置（.env、iKuai 导出、nginx/证书） | 手工拷贝到 D 的加密盘 `configs/` | 同上 | 同上 |
| 上传证据/附件 | 随 `mysql_data` 卷；验收前 `docker run --rm -v nis_mysql_data:... tar` 整卷归档一次 | 同上 | 验收后 1 份 |

- 备份文件**不入仓库**（`.gitignore` 已排除 `backups/`）；
- `.env` 与备份文件分开存放：备份不含 `.env`，恢复时口令需另有保管；
- 演练/验收现场每天开始前与结束后各执行一次 `backup.sh`。

## 使用

```bash
# 备份（自动生成 .sha256 与摘要）
deploy/backup/backup.sh

# 校验备份文件未损坏
gzip -t deploy/backup/backups/<file>.sql.gz && sha256sum -c <file>.sql.gz.sha256

# 恢复到当前 nis 实例（交互确认 + 恢复前自动前滚备份）
deploy/backup/restore.sh deploy/backup/backups/<file>.sql.gz

# 恢复到隔离测试实例（Issue #18 验收方式：另一环境核对）
docker run -d --name nis-restore-test -e MYSQL_ROOT_PASSWORD=<同口令> mysql:8.4
RESTORE_CONTAINER=nis-restore-test CONFIRM=YES \
  deploy/backup/restore.sh deploy/backup/backups/<file>.sql.gz
```

## 恢复后核对清单（人工）

1. Schema 清单 = 7 个 `nis_*`；
2. `nis_iam.users`：演示账号数与备份摘要一致；
3. `nis_recon.recon_records` / `nis_analysis.analysis_reports` /
   `nis_decision.commands` / `nis_execution.execution_assignments`：
   行数与备份摘要一致；
4. `nis_audit.audit_events`：行数一致（审计不可缺失）；
5. 账号仍存在且权限正确：`SHOW GRANTS FOR 'nis_audit_app'@'%';`
   应只有 `SELECT, INSERT`；
6. 应用级验证：`deploy/nis.sh up` 后用种子账号登录并查看一条记录详情。

## 恢复耗时记录（每次实测后填写）

| 日期 | 备份大小 | 恢复目标 | 耗时 | 结果 | 记录人 |
|---|---|---|---|---|---|
| 2026-10-27 | 832 KB（7 Schema+账号+种子 users 表 2 行） | 本机隔离容器 nis-restore-test | 2-3s | 通过：Schema/行数/HEX 中文数据/14 账号/audit 授权逐项一致（快照见 test-report §6） | D |

## 已知限制

- `mysqldump` 为逻辑备份，恢复速度随数据量增长；课程数据量（<100MB）下分钟级；
- 备份不含宿主机 `.env` 与 JWT 密钥，需按"备份范围"表另行保管；
- `--single-transaction` 保证 InnoDB 一致性快照，但不含运行中容器的内存态
  （连接、事务）——恢复后应用需重启（`deploy/nis.sh up`）；
- 未实测的恢复不得在报告中写"已验证"。
