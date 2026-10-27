#!/usr/bin/env bash
# NIS 数据库恢复（Issue #18）
# 用法：
#   deploy/backup/restore.sh <备份文件.sql.gz>             恢复到当前 nis mysql
#   CONFIRM=YES deploy/backup/restore.sh <file>            跳过交互确认（脚本调用）
#   RESTORE_CONTAINER=<name> deploy/backup/restore.sh <f>  恢复到指定容器（测试实例）
#
# 安全机制：
#   1. 恢复前对目标容器做一次自动备份（前滚保护）；
#   2. 交互确认（输入目标容器名）；
#   3. 恢复后自动核对 Schema 清单与关键表行数并输出摘要。
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"
FILE="${1:-}"
CONTAINER="${RESTORE_CONTAINER:-nis-mysql-1}"
ROOT_ENV="$ROOT/.env"

fail() { echo "[restore] 错误：$1" >&2; exit 1; }

[[ -f "$FILE" ]] || fail "备份文件不存在：$FILE（需 .sql.gz）"
[[ "$FILE" == *.sql.gz ]] || fail "仅支持 .sql.gz 备份文件"
[[ -f "$ROOT_ENV" ]] || fail "缺少 $ROOT_ENV"
docker inspect "$CONTAINER" >/dev/null 2>&1 || fail "目标容器不存在：$CONTAINER"

get_root_pw() {
  docker exec "$CONTAINER" sh -c 'echo "$MYSQL_ROOT_PASSWORD"'
}

mysql_exec() {
  docker exec -i "$CONTAINER" sh -c \
    'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$@"' _ "$@"
}

# 校验完整性（解压流 CRC）后再动库
echo "[restore] 校验备份完整性……"
gzip -t "$FILE" || fail "gzip 完整性校验失败，文件损坏"

if [[ "$CONFIRM" != "YES" ]]; then
  echo "即将把 $FILE 恢复到容器 $CONTAINER（会覆盖同名数据库）。"
  read -r -p "确认请输入容器名 [$CONTAINER]：" ans
  [[ "$ans" == "$CONTAINER" ]] || fail "确认失败，已取消"
fi

# 前滚保护：先备份当前目标状态
PRE="$DEPLOY_DIR/backups/pre-restore-$CONTAINER-$(date +%Y%m%d-%H%M%S).sql.gz"
mkdir -p "$DEPLOY_DIR/backups"
docker exec "$CONTAINER" sh -c \
  'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction \
     --routines --events --triggers --all-databases' | gzip -9 > "$PRE"
echo "[restore] 已备份当前状态：$PRE"

echo "[restore] 开始恢复……"
START=$(date +%s)
docker exec -i "$CONTAINER" sh -c \
  'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' < <(gzip -dc "$FILE")
# mysql.* 授权表以普通表方式恢复，必须重载权限缓存，账号授权才生效
docker exec "$CONTAINER" sh -c \
  'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "FLUSH PRIVILEGES;"' 2>/dev/null
END=$(date +%s)

echo "[restore] 完成，耗时 $((END-START))s。核对结果："
echo "[restore] Schema 与表数量："
mysql_exec -e "
SELECT table_schema AS schema_name, COUNT(*) AS tables
FROM information_schema.tables
WHERE table_schema LIKE 'nis_%'
GROUP BY table_schema ORDER BY table_schema;" 2>/dev/null
echo "[restore] 关键业务表行数（逐表独立统计，未迁移的表自动跳过）："
for pair in "nis_iam.users" "nis_recon.recon_records" "nis_analysis.analysis_reports" \
            "nis_decision.commands" "nis_execution.execution_assignments" \
            "nis_audit.audit_events"; do
  rows="$(docker exec "$CONTAINER" sh -c \
    "exec mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -N -e 'SELECT COUNT(*) FROM $pair;'" 2>/dev/null || true)"
  [[ -n "$rows" ]] && echo "  $pair = $rows" || echo "  $pair =（表不存在，未迁移属预期）"
done
echo "[restore] 授权抽查（audit 只允许 SELECT/INSERT）："
audit_user="${RESTORE_AUDIT_USER:-nis_audit_app}"
docker exec -i "$CONTAINER" sh -c \
  'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N' <<SQL 2>/dev/null \
  || echo "  （查询失败，人工核对）"
SHOW GRANTS FOR '$audit_user'@'%';
SQL
echo "[restore] 摘要结束。请按 backup/README.md 的核对清单人工抽查关键记录。"
