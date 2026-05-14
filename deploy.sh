#!/bin/bash
# ArchiPlan AI — Déploiement automatique via webhook GitHub
# Exécuté quand Claude Code (ou n'importe qui) push sur le repo
set -euo pipefail

REPO_DIR="/root/archiplan3d"
LOG_FILE="/root/archiplan3d/app/logs/deploy.log"
PYTHON_BIN="${PYTHON_BIN:-}"

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
log "📦 pip install..."
"$PYTHON_BIN" -m pip install -r requirements.txt -q 2>&1 | tee -a "$LOG_FILE"

# 3. Tests
log "🧪 pytest..."
if "$PYTHON_BIN" -m pytest tests/ -q 2>&1 | tee -a "$LOG_FILE"; then
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
nohup "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port 9090 > app/logs/uvicorn.log 2>&1 &
sleep 2

# 5. Vérification
if curl -sf http://localhost:9090/api/health > /dev/null 2>&1; then
    log "✅ Déploiement réussi — serveur en ligne"
else
    log "❌ ÉCHEC — le serveur ne répond pas"
    exit 1
fi
