#!/usr/bin/env bash
# NIS 数据库全实例备份（Issue #18）
# 产出：backups/nis-<时间戳>.sql.gz + 同名 .sha256 + 摘要（stdout）
# 说明：经 docker compose exec 在 mysql 容器内执行 mysqldump；
#       备份文件只落在本机 backups/（gitignore），不进入 Git。
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"
OUT_DIR="$DEPLOY_DIR/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$OUT_DIR/nis-$STAMP.sql.gz"

mkdir -p "$OUT_DIR"

# shellcheck disable=SC2086
docker compose --project-name nis --env-file "$ROOT/.env" \
  -f "$DEPLOY_DIR/docker-compose.yml" exec -T mysql sh -c \
  'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction \
     --routines --events --triggers --all-databases' \
  | gzip -9 > "$OUT"

sha256sum "$OUT" > "$OUT.sha256"

# 摘要：大小 + 包含的 NIS Schema（从备份中提取 CREATE DATABASE 行）
echo "[backup] 文件：$OUT"
echo "[backup] 大小：$(du -h "$OUT" | cut -f1)"
echo "[backup] NIS Schema 清单："
zgrep -o 'CREATE DATABASE[^;]*`nis_[^`]*`' "$OUT" | sed 's/.*`\(nis_[^`]*\)`.*/  - \1/' | sort -u
echo "[backup] 校验：$OUT.sha256"
