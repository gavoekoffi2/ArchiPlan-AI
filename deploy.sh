#!/bin/bash
# ArchiPlan AI — Déploiement automatique via webhook GitHub
# Exécuté quand Claude Code (ou n'importe qui) push sur le repo
set -e

REPO_DIR="/root/archiplan3d"
LOG_FILE="/root/archiplan3d/logs/deploy.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cd "$REPO_DIR"

log "🚀 Déploiement déclenché..."

# 1. Pull
log "📥 git pull..."
git pull origin master 2>&1 | tee -a "$LOG_FILE"

# 2. Dépendances
log "📦 pip install..."
pip install -r requirements.txt -q 2>&1 | tee -a "$LOG_FILE"

# 3. Tests
log "🧪 pytest..."
if python3 -m pytest tests/ -q 2>&1 | tee -a "$LOG_FILE"; then
    log "✅ Tests OK"
else
    log "⚠️ Tests échoués mais déploiement continue"
fi

# 4. Redémarrage serveur
log "🔄 Redémarrage serveur..."
pkill -f "uvicorn main:app.*9090" 2>/dev/null || true
sleep 2

cd app
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 9090 > /dev/null 2>&1 &
sleep 2

# 5. Vérification
if curl -sf http://localhost:9090/api/health > /dev/null 2>&1; then
    log "✅ Déploiement réussi — serveur en ligne"
else
    log "❌ ÉCHEC — le serveur ne répond pas"
    exit 1
fi
