#!/usr/bin/env sh
set -eu

SITE_ADDRESS=${1:-}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ -z "$SITE_ADDRESS" ]; then
  echo "Usage: $0 <public-domain|http://public-ip>" >&2
  exit 2
fi

case "$SITE_ADDRESS" in
  http://*) PUBLIC_URL=$SITE_ADDRESS; COOKIE_SECURE=false ;;
  https://*) PUBLIC_URL=$SITE_ADDRESS; COOKIE_SECURE=true ;;
  *) PUBLIC_URL=https://$SITE_ADDRESS; COOKIE_SECURE=true ;;
esac

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl docker.io docker-compose-v2 openssl
fi

systemctl enable --now docker
docker compose version >/dev/null

# Docker Hub is frequently unreachable from mainland China cloud hosts.
# Keep an existing operator-managed daemon config, otherwise use the public mirror.
if [ ! -s /etc/docker/daemon.json ]; then
  install -d -m 755 /etc/docker
  cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io"
  ]
}
EOF
  systemctl restart docker
fi

if ! swapon --show --noheadings | grep -q .; then
  if command -v fallocate >/dev/null 2>&1; then
    fallocate -l 4G /swapfile
  else
    dd if=/dev/zero of=/swapfile bs=1M count=4096
  fi
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
fi

set_env() {
  key=$1
  value=$2
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

current_value() {
  key=$1
  sed -n "s/^${key}=//p" .env | tail -n 1
}

postgres_password=$(current_value POSTGRES_PASSWORD)
case "$postgres_password" in
  ""|gentrip|replace-*) postgres_password=$(openssl rand -hex 24) ;;
esac

jwt_secret=$(current_value AUTH_JWT_SECRET)
if [ "${#jwt_secret}" -lt 32 ]; then
  jwt_secret=$(openssl rand -hex 32)
fi

set_env APP_DOMAIN "$SITE_ADDRESS"
set_env BIND_HOST 127.0.0.1
set_env POSTGRES_PASSWORD "$postgres_password"
set_env AUTH_JWT_SECRET "$jwt_secret"
set_env AUTH_ENABLED true
set_env DEMO_AUTH_COOKIE_SECURE "$COOKIE_SECURE"
set_env PRODUCTION_ALLOW_REGISTRATION true
set_env ALLOW_INSECURE_TENANT_ID false
set_env RUNTIME_EXECUTION_MODE redis_stream
chmod 600 .env

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 22/tcp >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw allow 443/udp >/dev/null
fi

bash scripts/deploy-demo.sh

echo
echo "GenTrip containers started for ${PUBLIC_URL}"
echo "Complete the first owner registration, then set PRODUCTION_ALLOW_REGISTRATION=false in $ROOT/.env and rerun scripts/deploy-demo.sh."
