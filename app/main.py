"""
ArchiPlan AI - Backend FastAPI
Analyse IA de plans 2D → génération modèle 3D → visite virtuelle
"""
import os
import json
import base64
import re
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import httpx

# ─── LOAD ENV ───────────────────────────────────────────────────────
def load_dotenv():
    """Charge les variables depuis ~/.hermes/.env"""
    for env_path in [
        Path.home() / ".hermes" / ".env",
        Path("/root/.hermes/.env"),
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

app = FastAPI(title="ArchiPlan AI", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
UPLOADS = BASE_DIR / "uploads"
OUTPUT = BASE_DIR / "output"
STATIC = BASE_DIR / "static"

for d in [UPLOADS, OUTPUT]:
    d.mkdir(exist_ok=True)

# OpenRouter config
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ─── ROUTES ────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.post("/api/analyze-plan")
async def analyze_plan(file: UploadFile = File(...)):
    """Upload un plan 2D → l'IA l'analyse et extrait la structure"""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Seules les images sont acceptées (PNG, JPG, WEBP)")

    # Sauvegarder le fichier
    ext = file.filename.split(".")[-1] if "." in (file.filename or "") else "png"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"plan_{timestamp}.{ext}"
    filepath = UPLOADS / filename

    content = await file.read()
    filepath.write_bytes(content)

    # Encoder en base64 pour l'IA
    img_b64 = base64.b64encode(content).decode()

    # Analyse IA
    try:
        analysis = await ai_analyze_floor_plan(img_b64, ext)
    except Exception as e:
        raise HTTPException(500, f"Erreur IA: {str(e)}")

    # Sauvegarder l'analyse
    analysis_path = OUTPUT / f"{filepath.stem}_analysis.json"
    analysis_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))

    return {
        "status": "success",
        "file_id": filepath.stem,
        "filename": filename,
        "analysis": analysis,
    }


@app.post("/api/build-3d")
async def build_3d(request: dict):
    """Génère le modèle 3D à partir de l'analyse IA"""
    analysis = request.get("analysis")
    if not analysis:
        raise HTTPException(400, "Analyse requise")

    model_3d = generate_3d_model(analysis)

    # Sauvegarder
    file_id = request.get("file_id", "model")
    model_path = OUTPUT / f"{file_id}_3d.json"
    model_path.write_text(json.dumps(model_3d, indent=2))

    return {
        "status": "success",
        "model": model_3d,
        "file_id": file_id,
    }


@app.get("/api/model/{file_id}")
async def get_model(file_id: str):
    """Récupère un modèle 3D généré"""
    model_path = OUTPUT / f"{file_id}_3d.json"
    if not model_path.exists():
        raise HTTPException(404, "Modèle non trouvé")
    return JSONResponse(json.loads(model_path.read_text()))


@app.get("/api/demo-model")
async def demo_model():
    """Retourne un modèle de démo pré-construit"""
    demo = generate_demo_house()
    return {"status": "success", "model": demo}


# ─── IA ANALYSIS ───────────────────────────────────────────────────

async def ai_analyze_floor_plan(img_b64: str, ext: str) -> dict:
    """Utilise Claude/GPT-4V pour analyser le plan"""
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext.lower(), "image/png")

    prompt = """Tu es un expert en architecture. Analyse ce plan 2D et retourne UNIQUEMENT un objet JSON valide, sans texte avant ni après :

{
  "rooms": [
    {"name": "Salon", "x": 0, "z": 0, "width": 5, "depth": 4},
    ...
  ],
  "walls": [
    {"x1": 0, "z1": 0, "x2": 5, "z2": 0},
    ...
  ],
  "doors": [
    {"x": 2.3, "z": 0, "rotation": 0, "width": 0.9},
    ...
  ],
  "windows": [
    {"x": 1, "z": 4, "rotation": 0, "width": 1.2, "height": 1.2},
    ...
  ],
  "total_width": 10,
  "total_depth": 8,
  "floor_count": 1
}

RÈGLES CRITIQUES :
- Analyse RÉELLEMENT le plan visible dans l'image, n'invente rien
- Chaque pièce = un rectangle (nom, x, z, width, depth)
- Les murs = segments entre coordonnées (x1,z1,x2,z2)
- Portes = sur les murs, pas à l'intérieur, width ≈ 0.9m
- Fenêtres = sur les murs extérieurs, width 1-2m
- Dimensions totales : estime la taille réelle du bâtiment (10-20m typique)
- Coordonnées x,z partent du coin supérieur gauche du plan
- Hauteur des pièces par défaut : 2.7m
- Si l'image n'est PAS un plan d'architecture, retourne {"error": "Pas un plan de bâtiment reconnaissable"}
- Retourne UNIQUEMENT le JSON, sans markdown, sans commentaires"""

    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
        ]}
    ]

    # Gemini en premier (meilleur pour l'analyse de plans), puis GPT-4o, puis Claude
    for model in ["google/gemini-2.0-flash-001", "openai/gpt-4o", "anthropic/claude-sonnet-4"]:
        try:
            print(f"[IA] Trying model: {model}...")
            result = await call_openrouter(messages, model)
            print(f"[IA] Raw response ({model}): {result[:200]}...")
            parsed = extract_json(result)
            print(f"[IA] Parsed: rooms={len(parsed.get('rooms',[]))}, walls={len(parsed.get('walls',[]))}")
            if "error" not in parsed and "rooms" in parsed and len(parsed["rooms"]) > 0:
                print(f"[IA] SUCCESS with {model}")
                return parsed
            print(f"[IA] Invalid response from {model}")
        except Exception as e:
            print(f"[IA] {model} failed: {e}")
            continue

    # Fallback: analyse basique via OpenCV si dispo
    print("[IA] All models failed, trying basic CV analysis")
    basic = basic_cv_analysis(img_b64)
    if basic.get("rooms"):
        print(f"[IA] Basic CV found {len(basic['rooms'])} rooms")
        return basic

    print("[IA] Complete fallback to standard house")
    return generate_standard_house()


def basic_cv_analysis(img_b64: str) -> dict:
    """Analyse basique du plan par computer vision"""
    try:
        import cv2
        import numpy as np
        from io import BytesIO
        
        img_data = base64.b64decode(img_b64)
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        
        if img is None:
            return {}
        
        h, w = img.shape
        # Binarisation
        _, binary = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)
        # Dilater pour connecter les lignes
        kernel = np.ones((5,5), np.uint8)
        dilated = cv2.dilate(binary, kernel, iterations=2)
        # Trouver les contours
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        rooms = []
        scale = 0.05  # pixels → mètres (approximatif)
        for i, cnt in enumerate(contours[:12]):  # Max 12 pièces
            area = cv2.contourArea(cnt)
            if area < 500:  # Ignore les petits artefacts
                continue
            x, y, rw, rh = cv2.boundingRect(cnt)
            if rw < 20 or rh < 20:  # Minimum 1m
                continue
            rooms.append({
                "name": f"Pièce {i+1}",
                "x": round(x * scale, 1),
                "z": round(y * scale, 1),
                "width": round(rw * scale, 1),
                "depth": round(rh * scale, 1),
            })
        
        if rooms:
            return {
                "rooms": rooms,
                "walls": [],
                "doors": [],
                "windows": [],
                "total_width": round(w * scale, 1),
                "total_depth": round(h * scale, 1),
            }
    except Exception as e:
        print(f"[CV] Analysis failed: {e}")
    
    return {}


async def call_openrouter(messages: list, model: str) -> str:
    """Appelle l'API OpenRouter"""
    if not OPENROUTER_KEY:
        return "{}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 4096,
                "temperature": 0.1,
            },
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        raise Exception(data.get("error", {}).get("message", "Erreur API"))


def extract_json(text: str) -> dict:
    """Extrait un objet JSON d'une réponse texte"""
    # Nettoyer
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    # Trouver le premier { et le dernier }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    return {}


# ─── 3D MODEL GENERATOR ────────────────────────────────────────────

def generate_3d_model(analysis: dict) -> dict:
    """Convertit l'analyse IA en modèle 3D complet pour Three.js"""
    rooms = analysis.get("rooms", [])
    walls_data = analysis.get("walls", [])
    doors = analysis.get("doors", [])
    windows = analysis.get("windows", [])

    total_w = analysis.get("total_width", 12)
    total_d = analysis.get("total_depth", 10)
    wall_h = 2.7
    wall_thickness = 0.15

    model = {
        "metadata": {
            "total_width": total_w,
            "total_depth": total_d,
            "wall_height": wall_h,
            "units": "meters",
        },
        "rooms": [],
        "walls": [],
        "doors": [],
        "windows": [],
        "floor": None,
        "camera": {
            "position": {"x": total_w/2, "y": 8, "z": total_d/2},
            "lookAt": {"x": total_w/2, "y": 0, "z": total_d/2},
        }
    }

    # Floor (un grand plan)
    model["floor"] = {
        "width": total_w,
        "depth": total_d,
        "y": 0,
        "color": "#d4c5b2",
    }

    # Rooms (colorées différemment sur le sol)
    room_colors = ["#f4a460", "#7ec850", "#68a0d8", "#c080d0", "#50c8b8",
                   "#e8a040", "#60b880", "#5890d0", "#b870c8", "#48b8a8"]
    for i, room in enumerate(rooms):
        model["rooms"].append({
            "name": room.get("name", f"Pièce {i+1}"),
            "x": room.get("x", 0),
            "z": room.get("z", 0),
            "width": room.get("width", 3),
            "depth": room.get("depth", 3),
            "color": room_colors[i % len(room_colors)],
        })

    # Walls from wall data
    if walls_data:
        for w in walls_data:
            x1, z1 = w.get("x1", 0), w.get("z1", 0)
            x2, z2 = w.get("x2", 0), w.get("z2", 0)
            dx, dz = x2 - x1, z2 - z1
            length = (dx**2 + dz**2) ** 0.5
            angle = __import__("math").atan2(dz, dx)
            mid_x, mid_z = (x1 + x2) / 2, (z1 + z2) / 2

            model["walls"].append({
                "x": mid_x,
                "z": mid_z,
                "length": length,
                "height": wall_h,
                "thickness": wall_thickness,
                "rotation": round(angle, 4),
            })
    else:
        # Générer les murs à partir des pièces (périmètre)
        model["walls"] = generate_perimeter_walls(rooms, total_w, total_d, wall_h, wall_thickness)

    # Doors
    for d in doors:
        model["doors"].append({
            "x": d.get("x", 0),
            "z": d.get("z", 0),
            "y": 1.05,
            "width": d.get("width", 0.9),
            "height": 2.1,
            "rotation": d.get("rotation", 0),
            "color": "#8B7355",
        })

    # Windows
    for w in windows:
        model["windows"].append({
            "x": w.get("x", 0),
            "z": w.get("z", 0),
            "y": 1.2,
            "width": w.get("width", 1.2),
            "height": w.get("height", 1.2),
            "rotation": w.get("rotation", 0),
        })

    return model


def generate_perimeter_walls(rooms, total_w, total_d, wall_h, thickness):
    """Génère les murs du périmètre + murs intérieurs entre pièces"""
    walls = []
    # 4 murs extérieurs
    perimeter = [
        (total_w/2, thickness/2, total_w, 0),           # nord
        (total_w/2, total_d - thickness/2, total_w, 0),  # sud
        (thickness/2, total_d/2, total_d, 1.5708),       # ouest
        (total_w - thickness/2, total_d/2, total_d, 1.5708), # est
    ]
    for mx, mz, length, rot in perimeter:
        walls.append({
            "x": mx, "z": mz, "length": length,
            "height": wall_h, "thickness": thickness,
            "rotation": rot,
        })

    # Murs intérieurs entre pièces adjacentes
    room_lines = []
    for room in rooms:
        rx, rz, rw, rd = room.get("x",0), room.get("z",0), room.get("width",0), room.get("depth",0)
        # 4 bords de la pièce
        room_lines.append((rx, rz, rx+rw, rz))         # haut
        room_lines.append((rx+rw, rz, rx+rw, rz+rd))   # droite
        room_lines.append((rx, rz+rd, rx+rw, rz+rd))   # bas
        room_lines.append((rx, rz, rx, rz+rd))         # gauche

    # Détecter les segments partagés entre pièces → mur intérieur
    interior_walls = []
    for i, (ax1, az1, ax2, az2) in enumerate(room_lines):
        for j, (bx1, bz1, bx2, bz2) in enumerate(room_lines):
            if i >= j: continue
            # Vérifier si les segments sont colinéaires et adjacents
            if abs(ax1 - ax2) < 0.01 and abs(bx1 - bx2) < 0.01:
                # Segments verticaux
                if abs(ax1 - bx1) < 0.3:
                    min_z = min(az1, az2, bz1, bz2)
                    max_z = max(az1, az2, bz1, bz2)
                    overlap = min(az2, bz2) - max(az1, bz1) if az1 <= bz2 and bz1 <= az2 else 0
                    if overlap > 0.5:
                        interior_walls.append({
                            "x": ax1, "z": (min_z+max_z)/2,
                            "length": max_z - min_z,
                            "height": wall_h, "thickness": thickness,
                            "rotation": 1.5708,
                        })
            elif abs(az1 - az2) < 0.01 and abs(bz1 - bz2) < 0.01:
                # Segments horizontaux
                if abs(az1 - bz1) < 0.3:
                    min_x = min(ax1, ax2, bx1, bx2)
                    max_x = max(ax1, ax2, bx1, bx2)
                    overlap = min(ax2, bx2) - max(ax1, bx1) if ax1 <= bx2 and bx1 <= ax2 else 0
                    if overlap > 0.5:
                        interior_walls.append({
                            "x": (min_x+max_x)/2, "z": az1,
                            "length": max_x - min_x,
                            "height": wall_h, "thickness": thickness,
                            "rotation": 0,
                        })

    walls.extend(interior_walls)
    return walls


def generate_standard_house() -> dict:
    """Maison standard de fallback"""
    return {
        "rooms": [
            {"name": "Salon", "x": 0, "z": 0, "width": 5, "depth": 5},
            {"name": "Cuisine", "x": 5, "z": 0, "width": 3, "depth": 5},
            {"name": "Chambre 1", "x": 0, "z": 5, "width": 4, "depth": 3},
            {"name": "Chambre 2", "x": 4, "z": 5, "width": 4, "depth": 3},
            {"name": "SDB", "x": 8, "z": 0, "width": 2, "depth": 3},
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


def generate_demo_house() -> dict:
    """Maison de démonstration complète"""
    analysis = generate_standard_house()
    return generate_3d_model(analysis)


# ─── STATIC FILES ───────────────────────────────────────────────────

app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")

# ─── MAIN ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9090)
