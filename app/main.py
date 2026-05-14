"""
ArchiPlan AI — Backend FastAPI (production ready)
Analyse IA de plans 2D → modèle 3D → visite virtuelle.

Améliorations apportées :
- Logging fichier + console détaillé
- Cache d'analyse par hash SHA-256 de l'image (zéro re-analyse pour le même plan)
- Validation stricte de la sortie IA (refus du fallback silencieux)
- Rate limiting in-memory par IP sur /api/analyze-plan
- Gestion d'erreurs propre avec messages utilisateur français
- Endpoints utilitaires architecte : surface, estimation coût, export OBJ
"""
import os
import json
import base64
import hashlib
import hmac
import logging
import logging.handlers
import re
import secrets
import sqlite3
import time
import math
from collections import defaultdict, deque
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import httpx

# ─── PATHS & ENV ───────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
UPLOADS = BASE_DIR / "uploads"
OUTPUT = BASE_DIR / "output"
STATIC = BASE_DIR / "static"
LOGS = BASE_DIR / "logs"
CACHE = OUTPUT / ".cache"
DB_PATH = OUTPUT / "archiplan.sqlite3"

for d in [UPLOADS, OUTPUT, LOGS, CACHE]:
    d.mkdir(exist_ok=True, parents=True)


def load_dotenv() -> None:
    """Charge les variables depuis ~/.hermes/.env si présent."""
    for env_path in [
        Path.home() / ".hermes" / ".env",
        Path("/root/.hermes/.env"),
        BASE_DIR.parent / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text().split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and val and key not in os.environ:
                        os.environ[key] = val
            break


load_dotenv()

# ─── LOGGING ───────────────────────────────────────────────────────
logger = logging.getLogger("archiplan")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)

_file = logging.handlers.RotatingFileHandler(
    LOGS / "archiplan.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
)
_file.setFormatter(_fmt)
logger.addHandler(_file)
logger.propagate = False


# ─── APP CONFIG ────────────────────────────────────────────────────
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = [
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o",
    "anthropic/claude-sonnet-4",
]
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 Mo
RATE_LIMIT_PER_HOUR = int(os.environ.get("ARCHIPLAN_RATE_LIMIT", "60"))
SESSION_COOKIE = "archiplan_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
PASSWORD_ITERATIONS = 260_000

# Prix indicatif au m² (peut être surchargé par l'environnement ARCHIPLAN_PRICE_M2)
DEFAULT_PRICE_M2 = float(os.environ.get("ARCHIPLAN_PRICE_M2", "1800"))


def db() -> sqlite3.Connection:
    """Ouvre une connexion SQLite avec des lignes nommees."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Prepare la base locale : utilisateurs, sessions et projets sauvegardes."""
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                analysis_json TEXT,
                model_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "Adresse email invalide.")
    return email


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise HTTPException(400, "Le mot de passe doit contenir au moins 8 caracteres.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "created_at": row["created_at"],
    }


def create_session(response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, datetime.now().isoformat(), now + SESSION_MAX_AGE),
        )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,
    )


def current_user(request: Request) -> sqlite3.Row:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Connexion requise.")
    with db() as conn:
        row = conn.execute(
            """
            SELECT users.id, users.email, users.created_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, time.time()),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Session expiree. Reconnectez-vous.")
    return row

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("=" * 60)
    logger.info("ArchiPlan AI v%s démarré", app.version)
    logger.info("OpenRouter : %s", "configuré" if OPENROUTER_KEY else "MANQUANT")
    logger.info("Rate limit : %d req/h", RATE_LIMIT_PER_HOUR)
    logger.info("Prix m² défaut : %.0f €", DEFAULT_PRICE_M2)
    logger.info("Logs : %s", LOGS / "archiplan.log")
    logger.info("=" * 60)
    yield
    logger.info("ArchiPlan AI arrêté")


app = FastAPI(title="ArchiPlan AI", version="2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

# Rate-limit en mémoire : { ip: deque[timestamps] }
_rate_log: dict = defaultdict(lambda: deque(maxlen=RATE_LIMIT_PER_HOUR + 10))


def check_rate_limit(ip: str) -> bool:
    """Retourne True si la requête est autorisée, False sinon."""
    now = time.time()
    q = _rate_log[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_HOUR:
        return False
    q.append(now)
    return True


# ─── ROUTES ────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": app.version,
        "timestamp": datetime.now().isoformat(),
        "models": MODELS,
        "openrouter_configured": bool(OPENROUTER_KEY),
    }


@app.post("/api/auth/register")
async def register(payload: dict, response: Response):
    """Cree un compte local et ouvre une session."""
    email = normalize_email(payload.get("email", ""))
    password_hash = hash_password(payload.get("password", ""))
    now = datetime.now().isoformat()
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, now),
            )
            user_id = cur.lastrowid
            row = conn.execute(
                "SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Un compte existe deja avec cet email.")
    create_session(response, int(user_id))
    logger.info("Compte cree | user_id=%s | email=%s", user_id, email)
    return {"status": "success", "user": public_user(row)}


@app.post("/api/auth/login")
async def login(payload: dict, response: Response):
    """Connecte un utilisateur par email/mot de passe."""
    email = normalize_email(payload.get("email", ""))
    password = payload.get("password", "")
    with db() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, created_at FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(401, "Email ou mot de passe incorrect.")
    create_session(response, int(row["id"]))
    logger.info("Connexion utilisateur | user_id=%s | email=%s", row["id"], email)
    return {"status": "success", "user": public_user(row)}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    """Ferme la session courante."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "success"}


@app.get("/api/auth/me")
async def me(request: Request):
    """Retourne l'utilisateur connecte."""
    return {"status": "success", "user": public_user(current_user(request))}


def serialize_project(row: sqlite3.Row, include_payload: bool = False) -> dict:
    project = {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_payload:
        project["analysis"] = json.loads(row["analysis_json"]) if row["analysis_json"] else None
        project["model"] = json.loads(row["model_json"])
    return project


@app.get("/api/projects")
async def list_projects(request: Request):
    """Liste les projets de l'utilisateur connecte."""
    user = current_user(request)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, analysis_json, model_json, created_at, updated_at
            FROM projects
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user["id"],),
        ).fetchall()
    return {"status": "success", "projects": [serialize_project(r) for r in rows]}


@app.post("/api/projects")
async def save_project(request: Request, payload: dict):
    """Sauvegarde un projet utilisateur."""
    user = current_user(request)
    name = (payload.get("name") or "Projet ArchiPlan").strip()[:120]
    model = payload.get("model")
    if not isinstance(model, dict) or not model.get("rooms"):
        raise HTTPException(400, "Modele 3D requis pour sauvegarder le projet.")
    analysis = payload.get("analysis")
    now = datetime.now().isoformat()
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects(user_id, name, analysis_json, model_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                name,
                json.dumps(analysis, ensure_ascii=False) if analysis else None,
                json.dumps(model, ensure_ascii=False),
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT id, name, analysis_json, model_json, created_at, updated_at FROM projects WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    logger.info("Projet sauvegarde | user_id=%s | project_id=%s", user["id"], row["id"])
    return {"status": "success", "project": serialize_project(row, include_payload=True)}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int, request: Request):
    """Charge un projet sauvegarde."""
    user = current_user(request)
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, name, analysis_json, model_json, created_at, updated_at
            FROM projects
            WHERE id = ? AND user_id = ?
            """,
            (project_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Projet non trouve.")
    return {"status": "success", "project": serialize_project(row, include_payload=True)}


@app.put("/api/projects/{project_id}")
async def update_project(project_id: int, request: Request, payload: dict):
    """Met a jour le nom et/ou le contenu d'un projet."""
    user = current_user(request)
    fields = []
    values = []
    if "name" in payload:
        fields.append("name = ?")
        values.append((payload.get("name") or "Projet ArchiPlan").strip()[:120])
    if "analysis" in payload:
        fields.append("analysis_json = ?")
        values.append(json.dumps(payload.get("analysis"), ensure_ascii=False))
    if "model" in payload:
        model = payload.get("model")
        if not isinstance(model, dict) or not model.get("rooms"):
            raise HTTPException(400, "Modele 3D invalide.")
        fields.append("model_json = ?")
        values.append(json.dumps(model, ensure_ascii=False))
    if not fields:
        raise HTTPException(400, "Aucune modification fournie.")
    fields.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.extend([project_id, user["id"]])
    with db() as conn:
        cur = conn.execute(
            f"UPDATE projects SET {', '.join(fields)} WHERE id = ? AND user_id = ?",
            values,
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Projet non trouve.")
        row = conn.execute(
            "SELECT id, name, analysis_json, model_json, created_at, updated_at FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    return {"status": "success", "project": serialize_project(row, include_payload=True)}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int, request: Request):
    """Supprime un projet sauvegarde."""
    user = current_user(request)
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user["id"]),
        )
    if cur.rowcount == 0:
        raise HTTPException(404, "Projet non trouve.")
    return {"status": "success"}


@app.post("/api/analyze-plan")
async def analyze_plan(request: Request, file: UploadFile = File(...)):
    """Upload un plan 2D → l'IA l'analyse et extrait la structure."""
    client_ip = request.client.host if request.client else "unknown"

    if not check_rate_limit(client_ip):
        logger.warning("Rate limit hit for %s", client_ip)
        raise HTTPException(
            429,
            f"Trop de requêtes. Limite : {RATE_LIMIT_PER_HOUR}/heure. Réessayez plus tard.",
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Seules les images sont acceptées (PNG, JPG, WEBP).")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Fichier vide.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"Fichier trop volumineux ({len(content) // 1024} Ko). Maximum : 8 Mo."
        )

    # Hash de l'image → cache
    img_hash = hashlib.sha256(content).hexdigest()[:16]
    ext = (file.filename or "plan.png").rsplit(".", 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg", "webp"}:
        ext = "png"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"plan_{timestamp}_{img_hash[:8]}.{ext}"
    filepath = UPLOADS / filename
    filepath.write_bytes(content)

    logger.info(
        "Upload reçu | ip=%s | taille=%d Ko | hash=%s | nom=%s",
        client_ip, len(content) // 1024, img_hash, filename,
    )

    # Cache hit ?
    cache_file = CACHE / f"{img_hash}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            logger.info("CACHE HIT pour hash=%s — analyse réutilisée", img_hash)
            return {
                "status": "success",
                "file_id": filepath.stem,
                "filename": filename,
                "analysis": cached,
                "cached": True,
            }
        except Exception as e:
            logger.warning("Cache corrompu (%s), on relance l'analyse : %s", img_hash, e)

    img_b64 = base64.b64encode(content).decode()

    try:
        analysis = await ai_analyze_floor_plan(img_b64, ext, img_hash)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erreur IA pour hash=%s", img_hash)
        raise HTTPException(500, f"L'IA n'a pas pu analyser le plan : {e}")

    # Sauvegarder analyse + cache
    (OUTPUT / f"{filepath.stem}_analysis.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False)
    )
    cache_file.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))

    return {
        "status": "success",
        "file_id": filepath.stem,
        "filename": filename,
        "analysis": analysis,
        "cached": False,
    }


@app.post("/api/build-3d")
async def build_3d(payload: dict):
    """Génère le modèle 3D à partir de l'analyse IA."""
    analysis = payload.get("analysis")
    if not analysis or not isinstance(analysis, dict):
        raise HTTPException(400, "Analyse requise.")
    if not analysis.get("rooms"):
        raise HTTPException(400, "Analyse invalide : aucune pièce.")

    model_3d = generate_3d_model(analysis)
    file_id = payload.get("file_id", "model")
    safe_id = re.sub(r"[^A-Za-z0-9_\-]", "_", str(file_id))[:80] or "model"
    (OUTPUT / f"{safe_id}_3d.json").write_text(json.dumps(model_3d, indent=2))

    logger.info(
        "Modèle 3D généré | id=%s | pièces=%d | murs=%d",
        safe_id, len(model_3d["rooms"]), len(model_3d["walls"]),
    )
    return {"status": "success", "model": model_3d, "file_id": safe_id}


@app.get("/api/model/{file_id}")
async def get_model(file_id: str):
    safe_id = re.sub(r"[^A-Za-z0-9_\-]", "_", file_id)[:80]
    model_path = OUTPUT / f"{safe_id}_3d.json"
    if not model_path.exists():
        raise HTTPException(404, "Modèle non trouvé.")
    return JSONResponse(json.loads(model_path.read_text()))


@app.get("/api/demo-model")
async def demo_model():
    return {"status": "success", "model": generate_3d_model(generate_standard_house())}


@app.post("/api/estimate-cost")
async def estimate_cost(payload: dict):
    """Estime le coût de construction.
    Body : { "model": <model_3d>, "price_per_m2": <float optionnel> }
    """
    model = payload.get("model")
    if not model or not isinstance(model, dict):
        raise HTTPException(400, "Modèle 3D requis.")
    price = float(payload.get("price_per_m2") or DEFAULT_PRICE_M2)
    rooms = model.get("rooms", [])

    surface_habitable = sum(r.get("width", 0) * r.get("depth", 0) for r in rooms)
    meta = model.get("metadata", {})
    surface_plancher = meta.get("total_width", 0) * meta.get("total_depth", 0)
    cost = surface_habitable * price

    return {
        "surface_habitable_m2": round(surface_habitable, 2),
        "surface_plancher_m2": round(surface_plancher, 2),
        "price_per_m2": price,
        "total_cost_eur": round(cost, 2),
        "currency": "EUR",
        "details": {
            "rooms_count": len(rooms),
            "walls_count": len(model.get("walls", [])),
            "doors_count": len(model.get("doors", [])),
            "windows_count": len(model.get("windows", [])),
        },
    }


@app.get("/api/export-obj/{file_id}", response_class=PlainTextResponse)
async def export_obj(file_id: str):
    """Exporte le modèle 3D au format OBJ (Wavefront).
    Compatible avec Blender, SketchUp, etc.
    """
    safe_id = re.sub(r"[^A-Za-z0-9_\-]", "_", file_id)[:80]
    model_path = OUTPUT / f"{safe_id}_3d.json"
    if not model_path.exists():
        raise HTTPException(404, "Modèle non trouvé.")
    model = json.loads(model_path.read_text())
    obj_text = model_to_obj(model)
    return PlainTextResponse(
        obj_text,
        headers={"Content-Disposition": f'attachment; filename="{safe_id}.obj"'},
    )


# ─── IA ANALYSIS ───────────────────────────────────────────────────

PROMPT_ANALYSE = """Tu es un expert en architecture et en lecture de plans 2D.

OBJECTIF : analyser RIGOUREUSEMENT le plan visible dans l'image et produire un JSON structuré.

ÉTAPES À SUIVRE MENTALEMENT :
1. Identifie l'orientation et l'échelle visible (cotes, légende, mètres ou cm).
2. Repère le contour extérieur du bâtiment et estime sa largeur/profondeur en mètres.
3. Repère chaque pièce comme un rectangle approximatif (nom + position + dimensions).
4. Trace les murs comme segments (x1,z1)→(x2,z2) en mètres.
5. Repère les portes (ouvertures avec arc) et fenêtres (ouvertures dans murs extérieurs).
6. Si tu vois des cotes, utilise-les ; sinon estime par proportions.

FORMAT DE SORTIE (JSON STRICT, RIEN D'AUTRE) :
{
  "rooms": [
    {"name": "Salon", "type": "living", "x": 0, "z": 0, "width": 5.0, "depth": 4.0},
    {"name": "Cuisine", "type": "kitchen", "x": 5.0, "z": 0, "width": 3.0, "depth": 4.0}
  ],
  "walls": [
    {"x1": 0, "z1": 0, "x2": 10, "z2": 0},
    {"x1": 10, "z1": 0, "x2": 10, "z2": 8}
  ],
  "doors": [
    {"x": 2.3, "z": 0, "rotation": 0, "width": 0.9}
  ],
  "windows": [
    {"x": 1.0, "z": 4.0, "rotation": 0, "width": 1.2, "height": 1.2}
  ],
  "total_width": 10.0,
  "total_depth": 8.0,
  "scale_detected": true,
  "orientation": "N",
  "floor_count": 1
}

TYPES DE PIÈCES VALIDES : "living", "kitchen", "bedroom", "bathroom", "wc", "office", "hallway", "entrance", "storage", "garage", "dining", "other".

RÈGLES STRICTES :
- Coordonnées en mètres, origine = coin supérieur-gauche, axe x→droite, z→bas.
- Dimensions totales typiquement entre 8 et 25 mètres.
- Hauteur par défaut 2.7 m (n'apparaît pas dans la sortie).
- Portes : width entre 0.7 et 1.0 m, rotation 0 (horizontale) ou 1.5708 (verticale).
- Fenêtres : width entre 0.6 et 2.0 m.
- ANALYSE RÉELLEMENT le plan — n'invente pas une maison générique.
- Si l'image n'est PAS un plan d'architecture (photo, schéma autre), retourne : {"error": "not_a_floor_plan"}.
- Retourne UNIQUEMENT le JSON, sans markdown ```, sans commentaires, sans explication."""


async def ai_analyze_floor_plan(img_b64: str, ext: str, img_hash: str) -> dict:
    """Analyse vision via OpenRouter (Gemini → GPT-4o → Claude → CV)."""
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(ext.lower(), "image/png")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT_ANALYSE},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            ],
        }
    ]

    last_error = None
    for model in MODELS:
        try:
            logger.info("[IA %s] envoi (hash=%s)...", model, img_hash)
            raw = await call_openrouter(messages, model)
            logger.info("[IA %s] reçu %d caractères", model, len(raw))
            parsed = extract_json(raw)

            if parsed.get("error") == "not_a_floor_plan":
                logger.warning("[IA %s] image non reconnue comme plan", model)
                raise HTTPException(
                    400,
                    "Cette image ne semble pas être un plan d'architecture. "
                    "Téléversez un plan 2D (PNG/JPG)."
                )

            if validate_analysis(parsed):
                logger.info(
                    "[IA %s] SUCCESS — pièces=%d, murs=%d, portes=%d, fenêtres=%d",
                    model,
                    len(parsed.get("rooms", [])),
                    len(parsed.get("walls", [])),
                    len(parsed.get("doors", [])),
                    len(parsed.get("windows", [])),
                )
                # Marquer la source pour traçabilité
                parsed["_meta"] = {"source": model, "hash": img_hash}
                return parsed

            logger.warning("[IA %s] sortie invalide : %s", model, str(parsed)[:200])
            last_error = f"{model}: réponse invalide"
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("[IA %s] échec : %s", model, e)
            last_error = f"{model}: {e}"
            continue

    # Fallback : CV uniquement si TOUS les modèles ont vraiment échoué
    logger.warning("Tous les modèles IA ont échoué, tentative CV. Dernière erreur : %s", last_error)
    basic = basic_cv_analysis(img_b64)
    if basic.get("rooms"):
        basic["_meta"] = {"source": "opencv_fallback", "hash": img_hash}
        logger.info("[CV] %d pièces détectées par fallback", len(basic["rooms"]))
        return basic

    # Aucun fallback silencieux vers la maison standard — on remonte l'erreur
    raise HTTPException(
        502,
        "Impossible d'analyser ce plan automatiquement. Essayez avec une image plus nette "
        "(plan d'architecture, traits noirs sur fond clair, 1000-3000 px). "
        f"Détails techniques : {last_error or 'aucune réponse exploitable'}"
    )


def validate_analysis(parsed: dict) -> bool:
    """Vérifie que la sortie IA est exploitable."""
    if not isinstance(parsed, dict):
        return False
    rooms = parsed.get("rooms")
    if not isinstance(rooms, list) or len(rooms) == 0:
        return False
    for r in rooms:
        if not isinstance(r, dict):
            return False
        try:
            w = float(r.get("width", 0))
            d = float(r.get("depth", 0))
        except (TypeError, ValueError):
            return False
        if w <= 0.5 or d <= 0.5 or w > 50 or d > 50:
            return False
    try:
        tw = float(parsed.get("total_width", 0))
        td = float(parsed.get("total_depth", 0))
    except (TypeError, ValueError):
        return False
    if tw <= 0 or td <= 0 or tw > 200 or td > 200:
        return False
    return True


def basic_cv_analysis(img_b64: str) -> dict:
    """Fallback OpenCV — détection contours rectangulaires."""
    try:
        import cv2
        import numpy as np

        img_data = base64.b64decode(img_b64)
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return {}

        h, w = img.shape
        scale = max(8.0 / w, 8.0 / h)  # vise ~8m de large par défaut

        _, binary = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)
        kernel = np.ones((3, 3), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(cleaned, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        rooms: list = []
        seen: list = []
        for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
            area = cv2.contourArea(cnt)
            if area < 1000:
                break
            x, y, rw, rh = cv2.boundingRect(cnt)
            if rw < 30 or rh < 30:
                continue
            # Filtrer les doublons (zone très proche d'une déjà ajoutée)
            duplicate = False
            for sx, sy, sw, sh in seen:
                if abs(x - sx) < 20 and abs(y - sy) < 20 and abs(rw - sw) < 30:
                    duplicate = True
                    break
            if duplicate:
                continue
            seen.append((x, y, rw, rh))
            rooms.append({
                "name": f"Pièce {len(rooms) + 1}",
                "type": "other",
                "x": round(x * scale, 2),
                "z": round(y * scale, 2),
                "width": round(rw * scale, 2),
                "depth": round(rh * scale, 2),
            })
            if len(rooms) >= 10:
                break

        if not rooms:
            return {}
        return {
            "rooms": rooms,
            "walls": [],
            "doors": [],
            "windows": [],
            "total_width": round(w * scale, 2),
            "total_depth": round(h * scale, 2),
            "scale_detected": False,
        }
    except Exception as e:
        logger.warning("[CV] échec : %s", e)
        return {}


async def call_openrouter(messages: list, model: str) -> str:
    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY non configurée")
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://archiplan.local",
                "X-Title": "ArchiPlan AI",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 4096,
                "temperature": 0.1,
            },
        )
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(msg or f"HTTP {resp.status_code}")
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Réponse vide")
        return choices[0]["message"]["content"]


def extract_json(text: str) -> dict:
    """Extrait un objet JSON d'une réponse texte (tolère markdown)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Tentative de nettoyage : remplacer les apostrophes simples par doubles
            try:
                return json.loads(candidate.replace("'", '"'))
            except json.JSONDecodeError:
                pass
    return {}


# ─── 3D MODEL GENERATOR ────────────────────────────────────────────

ROOM_COLORS = [
    "#f4a460", "#7ec850", "#68a0d8", "#c080d0", "#50c8b8",
    "#e8a040", "#60b880", "#5890d0", "#b870c8", "#48b8a8",
]


def generate_3d_model(analysis: dict) -> dict:
    """Convertit l'analyse IA en modèle 3D complet pour Three.js."""
    rooms = analysis.get("rooms", [])
    walls_data = analysis.get("walls", [])
    doors = analysis.get("doors", [])
    windows = analysis.get("windows", [])

    total_w = float(analysis.get("total_width", 12))
    total_d = float(analysis.get("total_depth", 10))
    wall_h = 2.7
    wall_thickness = 0.15

    model = {
        "metadata": {
            "total_width": total_w,
            "total_depth": total_d,
            "wall_height": wall_h,
            "units": "meters",
            "source": (analysis.get("_meta") or {}).get("source", "manual"),
        },
        "rooms": [],
        "walls": [],
        "doors": [],
        "windows": [],
        "floor": {
            "width": total_w,
            "depth": total_d,
            "y": 0,
            "color": "#d4c5b2",
        },
        "camera": {
            "position": {"x": total_w / 2, "y": max(total_w, total_d) * 0.7, "z": total_d * 1.3},
            "lookAt": {"x": total_w / 2, "y": 0, "z": total_d / 2},
        },
    }

    for i, room in enumerate(rooms):
        model["rooms"].append({
            "name": room.get("name", f"Pièce {i + 1}"),
            "type": room.get("type", "other"),
            "x": float(room.get("x", 0)),
            "z": float(room.get("z", 0)),
            "width": float(room.get("width", 3)),
            "depth": float(room.get("depth", 3)),
            "color": room.get("color") or ROOM_COLORS[i % len(ROOM_COLORS)],
        })

    if walls_data:
        for w in walls_data:
            try:
                x1, z1 = float(w.get("x1", 0)), float(w.get("z1", 0))
                x2, z2 = float(w.get("x2", 0)), float(w.get("z2", 0))
            except (TypeError, ValueError):
                continue
            dx, dz = x2 - x1, z2 - z1
            length = math.hypot(dx, dz)
            if length < 0.3:
                continue
            angle = math.atan2(dz, dx)
            model["walls"].append({
                "x": (x1 + x2) / 2,
                "z": (z1 + z2) / 2,
                "length": length,
                "height": wall_h,
                "thickness": wall_thickness,
                "rotation": round(angle, 4),
            })
    else:
        model["walls"] = generate_perimeter_walls(
            model["rooms"], total_w, total_d, wall_h, wall_thickness
        )

    for d in doors:
        try:
            model["doors"].append({
                "x": float(d.get("x", 0)),
                "z": float(d.get("z", 0)),
                "y": 1.05,
                "width": float(d.get("width", 0.9)),
                "height": 2.1,
                "rotation": float(d.get("rotation", 0)),
                "color": "#8B7355",
            })
        except (TypeError, ValueError):
            continue

    for w in windows:
        try:
            model["windows"].append({
                "x": float(w.get("x", 0)),
                "z": float(w.get("z", 0)),
                "y": 1.2,
                "width": float(w.get("width", 1.2)),
                "height": float(w.get("height", 1.2)),
                "rotation": float(w.get("rotation", 0)),
            })
        except (TypeError, ValueError):
            continue

    return model


def generate_perimeter_walls(rooms, total_w, total_d, wall_h, thickness):
    """Génère les murs du périmètre + murs intérieurs entre pièces."""
    walls = []
    perimeter = [
        (total_w / 2, thickness / 2, total_w, 0),
        (total_w / 2, total_d - thickness / 2, total_w, 0),
        (thickness / 2, total_d / 2, total_d, math.pi / 2),
        (total_w - thickness / 2, total_d / 2, total_d, math.pi / 2),
    ]
    for mx, mz, length, rot in perimeter:
        walls.append({
            "x": mx, "z": mz, "length": length,
            "height": wall_h, "thickness": thickness, "rotation": rot,
        })

    interior_walls = []
    for i, r1 in enumerate(rooms):
        for j, r2 in enumerate(rooms):
            if i >= j:
                continue
            r1x2, r1z2 = r1["x"] + r1["width"], r1["z"] + r1["depth"]
            r2x2, r2z2 = r2["x"] + r2["width"], r2["z"] + r2["depth"]
            # Adjacence verticale
            if abs(r1x2 - r2["x"]) < 0.3 or abs(r2x2 - r1["x"]) < 0.3:
                z1 = max(r1["z"], r2["z"])
                z2 = min(r1z2, r2z2)
                if z2 - z1 > 0.5:
                    shared_x = r1x2 if abs(r1x2 - r2["x"]) < 0.3 else r2x2
                    interior_walls.append({
                        "x": shared_x, "z": (z1 + z2) / 2,
                        "length": z2 - z1,
                        "height": wall_h, "thickness": thickness,
                        "rotation": math.pi / 2,
                    })
            # Adjacence horizontale
            if abs(r1z2 - r2["z"]) < 0.3 or abs(r2z2 - r1["z"]) < 0.3:
                x1 = max(r1["x"], r2["x"])
                x2 = min(r1x2, r2x2)
                if x2 - x1 > 0.5:
                    shared_z = r1z2 if abs(r1z2 - r2["z"]) < 0.3 else r2z2
                    interior_walls.append({
                        "x": (x1 + x2) / 2, "z": shared_z,
                        "length": x2 - x1,
                        "height": wall_h, "thickness": thickness,
                        "rotation": 0,
                    })

    walls.extend(interior_walls)
    return walls


def generate_standard_house() -> dict:
    """Maison standard utilisée uniquement pour /api/demo-model."""
    return {
        "rooms": [
            {"name": "Salon", "type": "living", "x": 0, "z": 0, "width": 5, "depth": 5},
            {"name": "Cuisine", "type": "kitchen", "x": 5, "z": 0, "width": 3, "depth": 5},
            {"name": "Chambre 1", "type": "bedroom", "x": 0, "z": 5, "width": 4, "depth": 3},
            {"name": "Chambre 2", "type": "bedroom", "x": 4, "z": 5, "width": 4, "depth": 3},
            {"name": "SDB", "type": "bathroom", "x": 8, "z": 0, "width": 2, "depth": 3},
        ],
        "walls": [],
        "doors": [
            {"x": 4.55, "z": 0, "rotation": 0, "width": 0.9},
            {"x": 5.45, "z": 0, "rotation": 0, "width": 0.9},
            {"x": 0, "z": 2.3, "rotation": 1.57, "width": 0.9},
            {"x": 7, "z": 5, "rotation": 0, "width": 0.9},
            {"x": 8, "z": 1.5, "rotation": 1.57, "width": 0.9},
        ],
        "windows": [
            {"x": 1.5, "z": 0, "rotation": 0, "width": 1.5, "height": 1.2},
            {"x": 3.5, "z": 5, "rotation": 1.57, "width": 1.2, "height": 1.2},
            {"x": 0, "z": 1.5, "rotation": 1.57, "width": 1.2, "height": 1.2},
            {"x": 5.5, "z": 0, "rotation": 0, "width": 1.2, "height": 1.2},
        ],
        "total_width": 10,
        "total_depth": 8,
    }


# ─── OBJ EXPORT ────────────────────────────────────────────────────

def model_to_obj(model: dict) -> str:
    """Export simple au format Wavefront OBJ (murs, sol, pièces)."""
    lines = ["# ArchiPlan AI — Export OBJ", f"# Généré le {datetime.now().isoformat()}"]
    vertex_offset = 1  # OBJ indexe à partir de 1

    def add_box(cx, cy, cz, w, h, d, rot=0.0, name="box"):
        nonlocal vertex_offset
        cos_r, sin_r = math.cos(rot), math.sin(rot)
        hw, hh, hd = w / 2, h / 2, d / 2
        local = [
            (-hw, -hh, -hd), (hw, -hh, -hd), (hw, hh, -hd), (-hw, hh, -hd),
            (-hw, -hh, hd), (hw, -hh, hd), (hw, hh, hd), (-hw, hh, hd),
        ]
        lines.append(f"o {name}")
        for lx, ly, lz in local:
            wx = cx + lx * cos_r - lz * sin_r
            wz = cz + lx * sin_r + lz * cos_r
            wy = cy + ly
            lines.append(f"v {wx:.4f} {wy:.4f} {wz:.4f}")
        v = vertex_offset
        # 6 faces (12 triangles)
        faces = [
            (v, v + 1, v + 2, v + 3), (v + 4, v + 5, v + 6, v + 7),
            (v, v + 1, v + 5, v + 4), (v + 2, v + 3, v + 7, v + 6),
            (v + 1, v + 2, v + 6, v + 5), (v, v + 3, v + 7, v + 4),
        ]
        for a, b, c, d_ in faces:
            lines.append(f"f {a} {b} {c} {d_}")
        vertex_offset += 8

    meta = model.get("metadata", {})
    wall_h = meta.get("wall_height", 2.7)

    floor = model.get("floor") or {}
    if floor:
        add_box(
            floor.get("width", 10) / 2, -0.05, floor.get("depth", 8) / 2,
            floor.get("width", 10), 0.1, floor.get("depth", 8), 0, "sol"
        )

    for i, w in enumerate(model.get("walls", [])):
        add_box(
            w["x"], w.get("height", wall_h) / 2, w["z"],
            w["length"], w.get("height", wall_h), w.get("thickness", 0.15),
            w.get("rotation", 0), f"mur_{i}"
        )

    for i, d in enumerate(model.get("doors", [])):
        add_box(
            d["x"], d.get("y", 1.05), d["z"],
            0.18, d.get("height", 2.1), d.get("width", 0.9),
            d.get("rotation", 0), f"porte_{i}"
        )

    return "\n".join(lines) + "\n"


# ─── WEBHOOK DEPLOIEMENT AUTO ───────────────────────────────────────
import subprocess, threading

WEBHOOK_SECRET = os.environ.get("ARCHIPLAN_WEBHOOK_SECRET", "archiplan-deploy-2026")
DEPLOY_SCRIPT = BASE_DIR.parent / "deploy.sh"


def _run_deploy_async() -> None:
    """Lance le déploiement en arrière-plan (processus séparé)."""
    logger.info("🚀 Déploiement automatique déclenché via webhook")
    try:
        subprocess.Popen(
            ["/bin/bash", str(DEPLOY_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # détaché du processus serveur
        )
    except Exception as exc:
        logger.error("Échec lancement déploiement: %s", exc)


@app.post("/api/modify-plan")
async def modify_plan(payload: dict):
    """Modifie un plan via IA depuis une commande en langage naturel.

    Body : {
        "analysis": <analyse actuelle>,
        "instruction": "Ajoute une chambre 4x3 m avec lit et armoire"
    }
    Retourne l'analyse modifiée.
    """
    analysis = payload.get("analysis")
    instruction = (payload.get("instruction") or "").strip()
    if not analysis or not isinstance(analysis, dict):
        raise HTTPException(400, "Analyse requise.")
    if not instruction:
        raise HTTPException(400, "Instruction requise (ex: « ajoute une chambre »).")
    if len(instruction) > 1000:
        raise HTTPException(400, "Instruction trop longue (max 1000 caractères).")

    prompt = f"""Tu es un expert en architecture. Voici un plan 2D au format JSON :

{json.dumps(analysis, ensure_ascii=False, indent=2)}

L'utilisateur demande : « {instruction} »

INSTRUCTION : applique cette demande et retourne le JSON MODIFIÉ avec la même structure.
- Conserve toutes les pièces, murs, portes, fenêtres existants sauf si la demande dit de les supprimer.
- Si on ajoute une pièce, place-la sur un côté libre du bâtiment sans chevaucher.
- Ajuste total_width / total_depth si nécessaire.
- Mets un type ("living", "kitchen", "bedroom", "bathroom", "wc", "office", "hallway", "entrance", "storage", "garage", "dining", "other") sur chaque pièce.
- Si l'utilisateur précise des meubles, ajoute un tableau "furniture" dans la pièce concernée avec :
  [{{"type": "bed", "x": <relatif>, "z": <relatif>}}, ...]

Retourne UNIQUEMENT le JSON modifié, rien d'autre, sans markdown."""

    messages = [{"role": "user", "content": prompt}]

    last_error = None
    for model in MODELS:
        try:
            logger.info("[MODIFY] model=%s instruction=%s", model, instruction[:80])
            raw = await call_openrouter(messages, model)
            parsed = extract_json(raw)
            if validate_analysis(parsed):
                logger.info("[MODIFY] SUCCESS pièces=%d", len(parsed.get("rooms", [])))
                parsed["_meta"] = {"source": f"{model} (modify)", "instruction": instruction}
                return {"status": "success", "analysis": parsed}
            last_error = f"{model}: réponse invalide"
        except Exception as e:
            logger.warning("[MODIFY] %s : %s", model, e)
            last_error = str(e)

    raise HTTPException(502, f"Impossible d'appliquer la modification. {last_error or ''}")


@app.post("/api/deploy")
async def github_webhook(request: Request):
    """
    Webhook GitHub → déploiement automatique.
    Quand Claude Code push, GitHub appelle cette URL → le serveur se met à jour tout seul.
    """
    raw_body = await request.body()
    try:
        body = json.loads(raw_body)
    except Exception:
        raise HTTPException(400, "JSON attendu")

    # Vérification du secret (header X-Hub-Signature-256)
    signature = request.headers.get("X-Hub-Signature-256", "")
    if WEBHOOK_SECRET:
        import hmac, hashlib
        expected = "sha256=" + hmac.new(
            WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        logger.debug("Webhook: sig_recue=%s sig_attendue=%s body_len=%d",
                     signature[:30] if signature else "ABSENT",
                     expected[:30], len(raw_body))
        if not hmac.compare_digest(signature, expected):
            logger.warning("Webhook: signature invalide — recue=%s... attendue=%s... body_preview=%s",
                          signature[:50], expected[:50], raw_body[:80])
            raise HTTPException(403, "Signature invalide")

    # On ne déploie que pour les pushs sur master
    ref = body.get("ref", "")
    if ref != "refs/heads/master":
        return {"status": "ignored", "ref": ref, "reason": "pas master"}

    # Lancement asynchrone (ne bloque pas la réponse HTTP)
    threading.Thread(target=_run_deploy_async, daemon=True).start()

    return {"status": "deploying", "message": "Déploiement lancé — le serveur redémarre"}


# ─── STATIC FILES ───────────────────────────────────────────────────
# Middleware anti-cache pour éviter que le navigateur garde l'ancienne version
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    # Pas de cache pour les fichiers HTML (force le rechargement)
    if request.url.path == "/" or request.url.path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Middleware : forcer no-cache sur les fichiers HTML pour que le navigateur
# prenne TOUJOURS la dernière version après chaque déploiement.
@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith(".html") or path == "/" or path.endswith("/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9090, log_level="info")
