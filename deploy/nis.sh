#!/usr/bin/env bash
# NIS 部署助手：统一 compose 调用（固定项目名、根目录 .env 与 compose 文件）。
# 用法：
#   deploy/nis.sh up            启动全栈（--profile app），等价验收形态
#   deploy/nis.sh db            仅启动 mysql（B/C 开发期）
#   deploy/nis.sh down          停止全栈（保留数据卷）
#   deploy/nis.sh nuke          停止并删除数据卷（危险：清库）
#   deploy/nis.sh ps|logs ...   其余参数原样透传 docker compose
#   deploy/nis.sh gen-keys      生成 JWT 密钥对（已存在则跳过）
#   deploy/nis.sh verify        配置自检：compose 语法 + 变量齐全 + 密钥就位
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"

compose() {
  # 注意不用 --project-directory：compose 的相对路径（./mysql 等）按 compose
  # 文件所在目录（deploy/）解析，改根目录会把挂载点算错。
  docker compose --project-name nis \
    --env-file "$ROOT/.env" -f "$COMPOSE_FILE" "$@"
}

gen_keys() {
  mkdir -p "$DEPLOY_DIR/secrets"
  if [[ -s "$DEPLOY_DIR/secrets/jwt_private.pem" && -s "$DEPLOY_DIR/secrets/jwt_public.pem" ]]; then
    echo "JWT 密钥已存在，跳过（轮换请手工删除后重跑）"
    return
  fi
  echo "生成 JWT RS256 密钥对（仅保存在本机 deploy/secrets/，*.pem 不入 Git）"
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
    -out "$DEPLOY_DIR/secrets/jwt_private.pem" 2>/dev/null
  openssl pkey -in "$DEPLOY_DIR/secrets/jwt_private.pem" -pubout \
    -out "$DEPLOY_DIR/secrets/jwt_public.pem" 2>/dev/null
  chmod 600 "$DEPLOY_DIR/secrets/jwt_private.pem"
  echo "完成：deploy/secrets/jwt_private.pem / jwt_public.pem"
}

verify() {
  [[ -f "$ROOT/.env" ]] || { echo "缺少 $ROOT/.env（先 cp .env.example .env 并填值）"; exit 1; }
  compose config --quiet && echo "compose 语法与变量：OK"
  for f in jwt_private.pem jwt_public.pem; do
    [[ -s "$DEPLOY_DIR/secrets/$f" ]] || { echo "缺少 deploy/secrets/$f（先运行 gen-keys）"; exit 1; }
  done
  echo "JWT 密钥：OK"
  echo "提示：口令须满足 ^[A-Za-z0-9_-]{12,}$，否则 mysql 初始化会主动失败"
}

case "${1:-}" in
  up)    shift; compose up -d --profile app "$@" ;;
  db)    shift; compose up -d "$@" ;;
  down)  shift; compose --profile app down "$@" ;;
  nuke)  shift; compose --profile app down -v "$@" ;;
  gen-keys) gen_keys ;;
  verify) verify ;;
  "")    echo "用法：$0 {up|db|down|nuke|gen-keys|verify|ps|logs|...}"; exit 2 ;;
  *)     compose "$@" ;;
esac
