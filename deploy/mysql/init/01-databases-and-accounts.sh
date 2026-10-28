#!/bin/bash
# NIS 数据库初始化：建库、按 Schema 建账号、授权（data-model §12.1 账号矩阵）。
# 由 mysql 官方镜像首次启动时在 /docker-entrypoint-initdb.d 中执行。
# 注意：本脚本以子进程方式运行，入口点的 shell 函数（如 docker_process_sql）
# 不可用，必须自带 mysql 客户端调用；init 阶段临时服务器仅开 socket，
# root 口令已生效，用 --protocol=socket 直连。
#
# 账号规则（Issue #17 验收标准）：
#   - 一个 Schema 一个运行账号，仅授权本 Schema 的 DML；
#   - nis_audit 运行账号只授予 SELECT/INSERT，不授予 UPDATE/DELETE；
#   - 每个 Schema 另建独立迁移账号（DDL + DML），不进入运行时容器；
#   - 口令只经环境变量注入，本脚本不含任何真实口令。
set -euo pipefail

fail() { echo "[nis-init] 错误：$1" >&2; exit 1; }

# 口令强度约束：12 位以上，字符集限字母/数字/下划线/连字符。
# 该约束同时确保口令可安全嵌入 SQL（无引号/反斜杠等转义风险）。
check_pw() {
  local name="$1" value="$2"
  [[ -n "$value" ]] || fail "$name 未设置"
  [[ "$value" =~ ^[A-Za-z0-9_-]{12,}$ ]] \
    || fail "$name 不合规：至少 12 位，仅允许字母/数字/下划线/连字符（安全基线要求）"
}

run_sql() {
  mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" "$@"
}

# schema|运行账号|运行口令变量|迁移账号|迁移口令变量
SPEC="
nis_iam|${IAM_DB_USER:-nis_iam_app}|IAM_DB_PASSWORD|nis_iam_migrate|IAM_MIGRATE_PASSWORD
nis_recon|${RECON_DB_USER:-nis_recon_app}|RECON_DB_PASSWORD|nis_recon_migrate|RECON_MIGRATE_PASSWORD
nis_analysis|${ANALYSIS_DB_USER:-nis_analysis_app}|ANALYSIS_DB_PASSWORD|nis_analysis_migrate|ANALYSIS_MIGRATE_PASSWORD
nis_decision|${DECISION_DB_USER:-nis_decision_app}|DECISION_DB_PASSWORD|nis_decision_migrate|DECISION_MIGRATE_PASSWORD
nis_execution|${EXECUTION_DB_USER:-nis_execution_app}|EXECUTION_DB_PASSWORD|nis_execution_migrate|EXECUTION_MIGRATE_PASSWORD
nis_ai|${AI_DB_USER:-nis_ai_app}|AI_DB_PASSWORD|nis_ai_migrate|AI_MIGRATE_PASSWORD
nis_audit|${AUDIT_DB_USER:-nis_audit_app}|AUDIT_DB_PASSWORD|nis_audit_migrate|AUDIT_MIGRATE_PASSWORD
"

check_pw MYSQL_ROOT_PASSWORD "${MYSQL_ROOT_PASSWORD:-}"

echo "[nis-init] 开始建库与账号授权"
while IFS='|' read -r schema app_user app_pw_var mig_user mig_pw_var; do
  [ -z "$schema" ] && continue
  app_pw="${!app_pw_var:-}"
  mig_pw="${!mig_pw_var:-}"
  check_pw "$app_pw_var" "$app_pw"
  check_pw "$mig_pw_var" "$mig_pw"

  run_sql --database=mysql <<EOSQL
CREATE DATABASE IF NOT EXISTS \`$schema\`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- 运行账号：本 Schema DML；audit 额外收紧为只读改=SELECT+INSERT
CREATE USER IF NOT EXISTS '$app_user'@'%'
  IDENTIFIED BY '$app_pw';
ALTER USER '$app_user'@'%' IDENTIFIED BY '$app_pw';
EOSQL

  if [ "$schema" = "nis_audit" ]; then
    run_sql --database=mysql <<EOSQL
GRANT SELECT, INSERT ON \`$schema\`.* TO '$app_user'@'%';
EOSQL
    echo "[nis-init] $schema 运行账号仅授予 SELECT/INSERT（审计只追加）"
  else
    run_sql --database=mysql <<EOSQL
GRANT SELECT, INSERT, UPDATE, DELETE ON \`$schema\`.* TO '$app_user'@'%';
EOSQL
  fi

  run_sql --database=mysql <<EOSQL
-- 迁移账号：DDL + DML，仅迁移作业使用，不进运行时容器
CREATE USER IF NOT EXISTS '$mig_user'@'%'
  IDENTIFIED BY '$mig_pw';
ALTER USER '$mig_user'@'%' IDENTIFIED BY '$mig_pw';
GRANT ALL PRIVILEGES ON \`$schema\`.* TO '$mig_user'@'%';
EOSQL

  echo "[nis-init] $schema 完成（$app_user / $mig_user）"
done <<< "$SPEC"

run_sql --database=mysql <<EOSQL
FLUSH PRIVILEGES;
EOSQL

echo "[nis-init] 全部完成：7 个 Schema + 7 运行账号 + 7 迁移账号"
