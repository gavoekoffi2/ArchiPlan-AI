#!/bin/bash
# ArchiPlan AI — Déploiement automatique via webhook GitHub
# Exécuté quand Claude Code (ou n'importe qui) push sur le repo
set -euo pipefail

REPO_DIR="/root/archiplan3d"
LOG_FILE="/root/archiplan3d/app/logs/deploy.log"
PYTHON_BIN="${PYTHON_BIN:-}"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"
FRONTEND_DIR="${FRONTEND_DIR:-/var/www/archiplan}"
FRONTEND_PORT="${FRONTEND_PORT:-9091}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cd "$REPO_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

if [ -z "$PYTHON_BIN" ]; then
    if command -v python3.11 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3.11)"
    else
        PYTHON_BIN="$(command -v python3)"
    fi
fi

log "🚀 Déploiement déclenché..."
log "🐍 Python: $("$PYTHON_BIN" --version 2>&1)"

# 1. Pull
log "📥 git pull..."
git pull origin master 2>&1 | tee -a "$LOG_FILE"

# 2. Dépendances
if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "🧰 Création du venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
APP_PYTHON="$VENV_DIR/bin/python"

log "📦 pip install..."
"$APP_PYTHON" -m pip install -r requirements.txt -q 2>&1 | tee -a "$LOG_FILE"

# 3. Tests
log "🧪 pytest..."
if "$APP_PYTHON" -m pytest tests/ -q 2>&1 | tee -a "$LOG_FILE"; then
    log "✅ Tests OK"
else
    log "❌ Tests échoués — déploiement arrêté"
    exit 1
fi

# 4. Redémarrage serveur
log "🔄 Redémarrage serveur..."
pkill -f "uvicorn .*9090" 2>/dev/null || true
sleep 2

cd "$REPO_DIR"
nohup "$APP_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 9090 > app/logs/uvicorn.log 2>&1 &
sleep 2

# 5. Vérification
if curl -sf http://localhost:9090/api/health > /dev/null 2>&1; then
    log "✅ Déploiement réussi — serveur en ligne"
else
    log "❌ ÉCHEC — le serveur ne répond pas"
    exit 1
fi

# 6. Frontend statique VPS (Nginx dédié sur un port séparé)
if command -v nginx >/dev/null 2>&1; then
    log "🌐 Déploiement frontend statique..."
    rm -rf "$FRONTEND_DIR"
    mkdir -p "$FRONTEND_DIR"
    cp -a "$REPO_DIR/app/static/." "$FRONTEND_DIR/"

    cat > "$REPO_DIR/app/logs/nginx-frontend.conf" <<NGINX
worker_processes 1;
pid /run/archiplan-frontend-nginx.pid;

events {
    worker_connections 512;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;

    server {
        listen 0.0.0.0:${FRONTEND_PORT};
        server_name _;
        root ${FRONTEND_DIR};
        index index.html;

        location /api/ {
            proxy_pass http://127.0.0.1:9090/api/;
            proxy_http_version 1.1;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }

        location / {
            try_files \$uri \$uri/ /index.html;
            add_header Cache-Control "no-cache, no-store, must-revalidate";
            add_header Pragma "no-cache";
            add_header Expires "0";
        }
    }
}
NGINX

    nginx -t -c "$REPO_DIR/app/logs/nginx-frontend.conf" 2>&1 | tee -a "$LOG_FILE"
    if [ -f /run/archiplan-frontend-nginx.pid ]; then
        nginx -s stop -c "$REPO_DIR/app/logs/nginx-frontend.conf" 2>/dev/null || true
        sleep 1
    fi
    nginx -c "$REPO_DIR/app/logs/nginx-frontend.conf"
    if curl -sf "http://localhost:${FRONTEND_PORT}/" > /dev/null 2>&1; then
        log "✅ Frontend VPS en ligne — port ${FRONTEND_PORT}"
    else
        log "❌ ÉCHEC — frontend VPS indisponible sur ${FRONTEND_PORT}"
        exit 1
    fi
else
    log "⚠️ Nginx absent — frontend servi par FastAPI sur le port 9090 uniquement"
fi
