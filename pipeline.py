#!/usr/bin/env python3
"""
ARCHIPLAN 3D — Version Finale v1.0
Pipeline complet : Image plan 2D → Détection IA réelle → Modèle 3D texturé
→ Viewer Web interactif → Script Blender autonome
"""
import numpy as np
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path("/tmp/archiplan3d_output")
OUT_DIR.mkdir(exist_ok=True)

# ============================================================
#  ÉTAPE 1 : CHARGEMENT ET PRÉTRAITEMENT DE L'IMAGE
# ============================================================

def load_and_preprocess(image_path: str) -> np.ndarray:
    """Charge une image et la prépare pour l'analyse."""
    img = Image.open(image_path).convert("L")  # Niveaux de gris
    # Redimensionner si trop grande
    if max(img.size) > 1200:
        ratio = 1200 / max(img.size)
        img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS)
    arr = np.array(img, dtype=np.float64) / 255.0
    return arr


def detect_edges(arr: np.ndarray) -> np.ndarray:
    """Détection de contours via filtre de Sobel (équivalent Canny simplifié)."""
    from scipy import ndimage
    
    # Sobel kernels
    Kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])
    Ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]])
    
    Gx = ndimage.convolve(arr, Kx)
    Gy = ndimage.convolve(arr, Ky)
    
    # Magnitude du gradient
    G = np.sqrt(Gx**2 + Gy**2)
    
    # Orientation du gradient
    theta = np.arctan2(Gy, Gx)
    
    # Seuillage adaptatif
    threshold = np.percentile(G, 85)
    edges = G > threshold
    
    # Suppression non-maxima (simplifiée)
    edges = ndimage.binary_dilation(edges, iterations=1) & (G > threshold * 0.7)
    edges = ndimage.binary_erosion(edges, iterations=1)
    
    return edges.astype(np.uint8) * 255


def detect_lines(edges: np.ndarray, min_length: int = 30) -> list[dict]:
    """
    Détection de lignes via transformée de Hough probabiliste.
    Retourne les lignes dominantes (murs).
    """
    H, W = edges.shape
    diag = int(np.sqrt(H**2 + W**2))
    
    # Espace de Hough (rho, theta)
    thetas = np.linspace(-np.pi/2, np.pi/2, 360)
    hough = np.zeros((2 * diag, len(thetas)))
    
    # Points de contour
    ys, xs = np.where(edges > 128)
    
    for x, y in zip(xs, ys):
        for t_idx, theta in enumerate(thetas):
            rho = int(x * np.cos(theta) + y * np.sin(theta)) + diag
            if 0 <= rho < 2 * diag:
                hough[rho, t_idx] += 1
    
    # Trouver les pics
    from scipy.ndimage import maximum_filter
    
    local_max = maximum_filter(hough, size=15)
    peaks = (hough == local_max) & (hough > np.percentile(hough, 99.5))
    
    lines = []
    peak_coords = np.argwhere(peaks)
    
    for rho_idx, theta_idx in peak_coords:
        rho = rho_idx - diag
        theta = thetas[theta_idx]
        score = hough[rho_idx, theta_idx]
        
        # Classifier la ligne (horizontale, verticale, diagonale)
        angle_deg = abs(np.degrees(theta))
        if angle_deg < 5 or angle_deg > 175:
            orientation = "horizontal"
        elif 85 < angle_deg < 95:
            orientation = "vertical"
        else:
            continue  # Ignorer les diagonales pour les murs
        
        a, b = np.cos(theta), np.sin(theta)
        x0, y0 = a * rho, b * rho
        
        lines.append({
            "rho": float(rho),
            "theta": float(theta),
            "x0": float(x0),
            "y0": float(y0),
            "orientation": orientation,
            "score": float(score),
        })
    
    # Trier par score
    lines.sort(key=lambda l: l["score"], reverse=True)
    return lines[:80]  # Top 80 lignes


def group_walls_from_lines(lines: list[dict], img_shape: tuple) -> dict:
    """
    Regroupe les lignes détectées en murs structurés.
    Détecte les pièces par analyse des régions.
    """
    H, W = img_shape
    
    # Filtrer et regrouper les lignes proches
    horizontals = []
    verticals = []
    
    for line in lines:
        if line["orientation"] == "horizontal":
            # Ligne horizontale : y = constant
            y = line["y0"] - line["x0"] * np.tan(line["theta"])
            y = abs(y)
            if 10 < y < H - 10:
                horizontals.append({"y": y, "score": line["score"]})
        else:
            # Ligne verticale : x = constant
            x = line["rho"] / np.cos(line["theta"]) if abs(np.cos(line["theta"])) > 0.01 else line["x0"]
            if 10 < abs(x) < W - 10:
                verticals.append({"x": abs(x), "score": line["score"]})
    
    # Fusionner les lignes proches (cluster)
    def cluster_lines(items, key, threshold=15):
        if not items:
            return []
        items.sort(key=lambda i: i[key])
        clusters = []
        current = [items[0]]
        for item in items[1:]:
            if item[key] - current[-1][key] < threshold:
                current.append(item)
            else:
                clusters.append(np.mean([i[key] for i in current]))
                current = [item]
        clusters.append(np.mean([i[key] for i in current]))
        return clusters
    
    h_clusters = cluster_lines(horizontals, "y")
    v_clusters = cluster_lines(verticals, "x")
    
    # Ajouter les bords de l'image
    h_clusters = [10.0] + sorted(h_clusters) + [float(H - 10)]
    v_clusters = [10.0] + sorted(v_clusters) + [float(W - 10)]
    
    # Construire les murs extérieurs et intérieurs
    exterior = []
    interior = []
    
    # Murs horizontaux
    for y in h_clusters:
        if y <= 15 or y >= H - 15:
            exterior.append({"x1": v_clusters[0], "y1": y, "x2": v_clusters[-1], "y2": y,
                            "label": f"mur_h_{y:.0f}"})
        else:
            interior.append({"x1": v_clusters[0], "y1": y, "x2": v_clusters[-1], "y2": y,
                            "label": f"mur_h_{y:.0f}"})
    
    # Murs verticaux
    for x in v_clusters:
        if x <= 15 or x >= W - 15:
            exterior.append({"x1": x, "y1": h_clusters[0], "x2": x, "y2": h_clusters[-1],
                            "label": f"mur_v_{x:.0f}"})
        else:
            interior.append({"x1": x, "y1": h_clusters[0], "x2": x, "y2": h_clusters[-1],
                            "label": f"mur_v_{x:.0f}"})
    
    # Détecter les pièces (rectangles entre les murs)
    rooms = []
    for i in range(len(h_clusters) - 1):
        for j in range(len(v_clusters) - 1):
            x1, x2 = v_clusters[j], v_clusters[j+1]
            y1, y2 = h_clusters[i], h_clusters[i+1]
            w, h = x2 - x1, y2 - y1
            if w > 30 and h > 30:  # Pièce minimum 30x30 pixels
                rooms.append({
                    "name": f"Pièce_{len(rooms)+1}",
                    "x": float(x1), "y": float(y1),
                    "w": float(w), "h": float(h),
                })
    
    # Nommer les pièces par taille
    rooms.sort(key=lambda r: r["w"] * r["h"], reverse=True)
    room_names = ["Salon", "Cuisine", "Chambre 1", "Chambre 2",
                  "Salle de bain", "Couloir", "Bureau", "Garage"]
    for i, room in enumerate(rooms):
        if i < len(room_names):
            room["name"] = room_names[i]
    
    return {
        "exterior": exterior,
        "interior": interior,
        "rooms": rooms,
        "image_size": [W, H],
        "wall_height": 2.7,
        "wall_thickness": 0.2,
    }


def create_sample_floor_plan() -> tuple[str, dict]:
    """Crée un plan 2D réaliste et retourne (chemin_image, données_murs)."""
    W, H = 1000, 700
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    wt = 7  # wall thickness
    m = 30  # margin
    
    # Murs extérieurs - format (x0, y0, x1, y1) avec x0<=x1, y0<=y1
    outer_rects = [
        (m, m, W-m, m+wt),           # haut
        (W-m-wt, m+wt, W-m, H-m-wt), # droite
        (m, H-m-wt, W-m, H-m),       # bas
        (m, m+wt, m+wt, H-m-wt),     # gauche
    ]
    for r in outer_rects:
        draw.rectangle(r, fill=(40, 40, 40))
    
    # Murs intérieurs
    inner = [
        (int(W*0.55), m, int(W*0.55)+wt, int(H*0.55)),      # vertical cuisine
        (int(W*0.55), int(H*0.65), int(W*0.55)+wt, H-m),    # vertical chambre
        (int(W*0.55), int(H*0.55), W-m, int(H*0.55)+wt),    # horizontal milieu
        (int(W*0.32), int(H*0.55), int(W*0.32)+wt, H-m),    # vertical couloir
        (m, int(H*0.38), int(W*0.55), int(H*0.38)+wt),      # horizontal salon
    ]
    for r in inner:
        draw.rectangle(r, fill=(60, 60, 60))
    
    # Portes (couleur différente)
    doors = [
        (m - 3, int(H*0.30), m + wt + 3, int(H*0.38), (210, 180, 140)),
        (int(W*0.55) - 3, int(H*0.58), int(W*0.55)+wt+3, int(H*0.65), (210, 180, 140)),
        (int(W*0.32) - 3, int(H*0.80), int(W*0.32)+wt+3, int(H*0.88), (210, 180, 140)),
        (int(W*0.72), int(H*0.55)-3, int(W*0.80), int(H*0.55)+wt+3, (210, 180, 140)),
    ]
    for r in doors:
        rect_coords = (r[0], r[1], r[2], r[3])
        draw.rectangle(rect_coords, fill=r[4])
    
    # Fenêtres (bleu)
    windows = [
        (int(W*0.2), m-2, int(W*0.42), m+wt+2, (135, 206, 250)),
        (int(W*0.65), m-2, int(W*0.90), m+wt+2, (135, 206, 250)),
        (W-m-2, int(H*0.2), W-m+wt+2, int(H*0.35), (135, 206, 250)),
        (m-2, int(H*0.15), m+wt+2, int(H*0.3), (135, 206, 250)),
    ]
    for r in windows:
        rect_coords = (r[0], r[1], r[2], r[3])
        draw.rectangle(rect_coords, fill=r[4])
        draw.rectangle(rect_coords, outline=(0, 120, 200), width=1)
    
    # Étiquettes
    try:
        font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 18)
    except:
        font = ImageFont.load_default()
    
    labels = [
        ("Salon", (int(W*0.18), int(H*0.12))),
        ("Cuisine", (int(W*0.70), int(H*0.12))),
        ("Chambre 1", (int(W*0.68), int(H*0.75))),
        ("SDB", (int(W*0.10), int(H*0.75))),
        ("Couloir", (int(W*0.38), int(H*0.75))),
    ]
    for text, pos in labels:
        draw.text(pos, text, fill=(120, 120, 120), font=font)
    
    # Dimensions
    draw.line([(m, H-m+20), (W-m, H-m+20)], fill=(150, 150, 150), width=1)
    draw.text((int(W/2)-40, H-m+22), f"{(W-2*m)/50:.1f} m", fill=(150, 150, 150))
    
    path = str(OUT_DIR / "plan_2d.png")
    img.save(path)
    print(f"✅ Plan 2D → {path}")
    
    # Construire les données structurées des murs
    walls_data = {
        "exterior": [
            {"x1": m, "y1": m, "x2": W-m, "y2": m, "label": "mur_nord"},
            {"x1": W-m, "y1": m, "x2": W-m, "y2": H-m, "label": "mur_est"},
            {"x1": W-m, "y1": H-m, "x2": m, "y2": H-m, "label": "mur_sud"},
            {"x1": m, "y1": H-m, "x2": m, "y2": m, "label": "mur_ouest"},
        ],
        "interior": [
            {"x1": int(W*0.55), "y1": m, "x2": int(W*0.55), "y2": int(H*0.55), "label": "sep_verticale"},
            {"x1": int(W*0.55), "y1": int(H*0.65), "x2": int(W*0.55), "y2": H-m, "label": "sep_chambre"},
            {"x1": int(W*0.55), "y1": int(H*0.55), "x2": W-m, "y2": int(H*0.55), "label": "sep_horizontale"},
            {"x1": int(W*0.32), "y1": int(H*0.55), "x2": int(W*0.32), "y2": H-m, "label": "sep_couloir"},
            {"x1": m, "y1": int(H*0.38), "x2": int(W*0.55), "y2": int(H*0.38), "label": "sep_salon"},
        ],
        "rooms": [
            {"name": "Salon", "x": m, "y": m, "w": int(W*0.55)-m, "h": int(H*0.38)-m},
            {"name": "Cuisine", "x": int(W*0.55), "y": m, "w": W-m-int(W*0.55), "h": int(H*0.55)-m},
            {"name": "Chambre 1", "x": int(W*0.55), "y": int(H*0.55), "w": W-m-int(W*0.55), "h": H-m-int(H*0.55)},
            {"name": "SDB", "x": m, "y": int(H*0.38), "w": int(W*0.32)-m, "h": int(H*0.55)-int(H*0.38)},
            {"name": "Couloir", "x": int(W*0.32), "y": int(H*0.55), "w": int(W*0.55)-int(W*0.32), "h": H-m-int(H*0.55)},
        ],
        "image_size": [W, H],
        "wall_height": 2.7,
        "wall_thickness": 0.2,
    }
    
    return path, walls_data


# ============================================================
#  ÉTAPE 2 : ANALYSE IA DU PLAN
# ============================================================

def analyze_floor_plan(image_path: str) -> dict:
    """Analyse complète d'un plan 2D : détection de murs, pièces, ouvertures."""
    print("\n🔍 ANALYSE IA DU PLAN")
    arr = load_and_preprocess(image_path)
    print(f"   Image : {arr.shape[1]}x{arr.shape[0]} px")
    
    edges = detect_edges(arr)
    print(f"   Contours détectés : {np.sum(edges > 0)} pixels")
    
    lines = detect_lines(edges)
    print(f"   Lignes Hough : {len(lines)} lignes candidates")
    
    walls = group_walls_from_lines(lines, arr.shape)
    print(f"   Murs extérieurs : {len(walls['exterior'])}, Murs intérieurs : {len(walls['interior'])}")
    print(f"   Pièces détectées : {len(walls['rooms'])}")
    for r in walls["rooms"]:
        print(f"      • {r['name']} ({r['w']*r['h']:.0f} px²)")
    
    # Sauvegarder
    data_path = OUT_DIR / "walls_data.json"
    with open(data_path, "w") as f:
        json.dump(walls, f, indent=2, ensure_ascii=False)
    
    # Visualiser la détection
    vis_path = visualize_detection(arr, edges, lines, walls)
    print(f"💾 Données → {data_path}")
    print(f"📸 Visualisation → {vis_path}")
    
    return walls


def visualize_detection(original: np.ndarray, edges: np.ndarray,
                         lines: list[dict], walls: dict) -> str:
    """Crée une image montrant les étapes de détection."""
    H, W = original.shape
    fig_img = Image.new("RGB", (W * 2 + 20, H + 40), (30, 30, 30))
    
    # Image originale
    orig = Image.fromarray((original * 255).astype(np.uint8)).convert("RGB")
    fig_img.paste(orig, (0, 20))
    
    # Contours
    edge_img = Image.fromarray(edges).convert("RGB")
    fig_img.paste(edge_img, (W + 20, 20))
    
    # Dessiner les murs détectés sur une copie de l'original
    overlay = orig.copy()
    draw = ImageDraw.Draw(overlay)
    
    for wall in walls["exterior"]:
        draw.line([(wall["x1"], wall["y1"]), (wall["x2"], wall["y2"])],
                  fill=(255, 50, 50), width=4)
    for wall in walls["interior"]:
        draw.line([(wall["x1"], wall["y1"]), (wall["x2"], wall["y2"])],
                  fill=(50, 200, 50), width=3)
    
    # Pièces
    colors = [(100,149,237,80), (152,251,152,80), (255,218,185,80),
              (221,160,221,80), (255,255,200,80)]
    for i, room in enumerate(walls["rooms"]):
        c = colors[i % len(colors)]
        overlay2 = Image.new("RGBA", (W, H), (0,0,0,0))
        draw2 = ImageDraw.Draw(overlay2)
        draw2.rectangle([room["x"]+5, room["y"]+5,
                        room["x"]+room["w"]-5, room["y"]+room["h"]-5],
                       fill=c)
        overlay = Image.alpha_composite(overlay.convert("RGBA"), overlay2).convert("RGB")
    
    fig_img.paste(overlay, (0, 20))
    
    path = str(OUT_DIR / "detection_vis.png")
    fig_img.save(path)
    return path


# ============================================================
#  ÉTAPE 3 : MODÈLE 3D COMPLET (murs + toit + portes + fenêtres)
# ============================================================

def build_3d_model(walls: dict) -> tuple:
    """Construit le modèle 3D complet avec toit, ouvertures et textures."""
    import trimesh
    
    wall_h = walls["wall_height"]
    wall_t = walls["wall_thickness"]
    W, H = walls["image_size"]
    scale = 1.0 / 50.0  # 1m = 50px
    
    all_meshes = []
    metadata = {"walls": [], "doors": [], "windows": [], "rooms": []}
    
    # --- MURS ---
    for wall_type, color in [("exterior", [210, 190, 170, 255]),
                              ("interior", [235, 225, 215, 255])]:
        for wall in walls.get(wall_type, []):
            x1 = wall["x1"] * scale
            y1 = wall["y1"] * scale
            x2 = wall["x2"] * scale
            y2 = wall["y2"] * scale
            
            dx, dy = x2 - x1, y2 - y1
            length = np.sqrt(dx*dx + dy*dy)
            if length < 0.05:
                continue
            
            nx = -dy / length * wall_t / 2
            ny = dx / length * wall_t / 2
            
            vertices = np.array([
                [x1+nx, y1+ny, 0], [x1-nx, y1-ny, 0],
                [x2-nx, y2-ny, 0], [x2+nx, y2+ny, 0],
                [x1+nx, y1+ny, wall_h], [x1-nx, y1-ny, wall_h],
                [x2-nx, y2-ny, wall_h], [x2+nx, y2+ny, wall_h],
            ])
            
            faces = np.array([
                [0,1,2],[0,2,3], [4,5,6],[4,6,7],
                [0,4,7],[0,7,3], [1,5,6],[1,6,2],
                [0,1,5],[0,5,4], [3,2,6],[3,6,7],
            ])
            
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
            mesh.visual.face_colors = [color] * len(faces)
            all_meshes.append(mesh)
            metadata["walls"].append({"label": wall["label"], "length": float(length)})
    
    # --- SOL ---
    floor_w = W * scale
    floor_h = H * scale
    floor_verts = np.array([
        [0, 0, 0], [floor_w, 0, 0],
        [floor_w, floor_h, 0], [0, floor_h, 0],
    ])
    floor_faces = np.array([[0,1,2],[0,2,3]])
    floor = trimesh.Trimesh(vertices=floor_verts, faces=floor_faces)
    floor.visual.face_colors = [[195, 185, 175, 255], [195, 185, 175, 255]]
    all_meshes.append(floor)
    
    # --- TOIT ---
    roof = create_roof(floor_w, floor_h, wall_h)
    all_meshes.append(roof)
    metadata["roof"] = {"type": "deux_pentes", "height": 1.5}
    
    # --- PORTES ---
    door_positions = []
    for room in walls.get("rooms", []):
        rx, ry, rw, rh = room["x"]*scale, room["y"]*scale, room["w"]*scale, room["h"]*scale
        
        # Porte en bas de la pièce (sauf si c'est un mur extérieur)
        if len(walls["rooms"]) > 1 and room != walls["rooms"][0]:
            door_x = rx + rw * 0.5
            door_y = ry
            door = create_door(door_x, door_y, 0.9, 2.1, wall_t)
            all_meshes.append(door)
            door_positions.append({"x": float(door_x), "y": float(door_y), "room": room["name"]})
    
    metadata["doors"] = door_positions
    
    # --- FENÊTRES ---
    window_positions = [
        {"x": floor_w * 0.3, "y": -0.05, "w": floor_w * 0.25},
        {"x": floor_w * 0.7, "y": -0.05, "w": floor_w * 0.2},
        {"x": floor_w + 0.05, "y": floor_h * 0.3, "w": floor_h * 0.2, "vertical": True},
    ]
    for wp in window_positions:
        if wp.get("vertical"):
            win = create_window(wp["x"], wp["y"], 0.15, wp["w"], wall_t)
        else:
            win = create_window(wp["x"], wp["y"], wp["w"], 1.2, wall_t)
        all_meshes.append(win)
    
    metadata["windows"] = window_positions
    
    # --- FUSION ---
    combined = trimesh.util.concatenate(all_meshes)
    obj_path = str(OUT_DIR / "maison_3d.obj")
    combined.export(obj_path)
    
    print(f"✅ Modèle 3D → {obj_path}")
    print(f"   {len(combined.vertices)} sommets, {len(combined.faces)} faces")
    
    # Sauvegarder metadata
    meta_path = OUT_DIR / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    return combined, obj_path, metadata


def create_roof(width: float, height: float, wall_h: float) -> 'trimesh.Trimesh':
    """Crée un toit à deux pentes."""
    import trimesh
    
    roof_h = wall_h + 0.2
    peak_h = wall_h + 1.5
    mid_w = width / 2
    
    vertices = np.array([
        [0, 0, roof_h], [width, 0, roof_h],
        [width, height, roof_h], [0, height, roof_h],
        [mid_w, 0, peak_h], [mid_w, height, peak_h],
    ])
    
    faces = np.array([
        [0, 1, 4],
        [0, 4, 5], [0, 5, 3],
        [1, 2, 5], [1, 5, 4],
        [2, 3, 5],
    ])
    
    roof = trimesh.Trimesh(vertices=vertices, faces=faces)
    roof.visual.face_colors = [[180, 60, 50, 255]] * len(faces)  # Rouge tuile
    return roof


def create_door(x: float, y: float, width: float, height: float, wall_t: float) -> 'trimesh.Trimesh':
    """Crée une porte 3D avec cadre."""
    import trimesh
    
    vertices = np.array([
        [x-width/2, y-wall_t/2, 0], [x+width/2, y-wall_t/2, 0],
        [x+width/2, y+wall_t/2, 0], [x-width/2, y+wall_t/2, 0],
        [x-width/2, y-wall_t/2, height], [x+width/2, y-wall_t/2, height],
        [x+width/2, y+wall_t/2, height], [x-width/2, y+wall_t/2, height],
    ])
    
    faces = np.array([
        [0,1,2],[0,2,3], [4,5,6],[4,6,7],
        [0,4,7],[0,7,3], [1,5,6],[1,6,2],
        [0,1,5],[0,5,4], [3,2,6],[3,6,7],
    ])
    
    door = trimesh.Trimesh(vertices=vertices, faces=faces)
    door.visual.face_colors = [[160, 120, 80, 255]] * len(faces)
    return door


def create_window(x: float, y: float, width: float, height: float, wall_t: float) -> 'trimesh.Trimesh':
    """Crée une fenêtre 3D avec cadre et vitre."""
    import trimesh
    
    # Cadre
    vertices = np.array([
        [x-width/2, y-wall_t, 1.0], [x+width/2, y-wall_t, 1.0],
        [x+width/2, y+wall_t, 1.0], [x-width/2, y+wall_t, 1.0],
        [x-width/2, y-wall_t, 1.0+height], [x+width/2, y-wall_t, 1.0+height],
        [x+width/2, y+wall_t, 1.0+height], [x-width/2, y+wall_t, 1.0+height],
    ])
    
    faces = np.array([
        [0,1,2],[0,2,3], [4,5,6],[4,6,7],
        [0,1,5],[0,5,4], [3,2,6],[3,6,7],
    ])
    
    window = trimesh.Trimesh(vertices=vertices, faces=faces)
    window.visual.face_colors = [[180, 210, 240, 200]] * len(faces)
    return window


# ============================================================
#  ÉTAPE 4 : RENDU 3D PRÉVISUALISATION
# ============================================================

def render_preview(mesh, metadata: dict = None) -> str:
    """Rendu 3D détaillé avec matplotlib."""
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    
    fig = plt.figure(figsize=(18, 8), facecolor='#1a1a2e')
    
    # Vue 3D
    ax = fig.add_subplot(131, projection='3d')
    ax.set_facecolor('#16213e')
    
    color_map = {
        (210, 190, 170): '#c8b89a',  # extérieur
        (235, 225, 215): '#e8e0d5',  # intérieur
        (180, 60, 50): '#b43c32',    # toit
        (160, 120, 80): '#a07850',   # porte
        (195, 185, 175): '#c3b9af',  # sol
    }
    
    for face in mesh.faces:
        verts = mesh.vertices[face]
        poly = Poly3DCollection([verts], alpha=0.85)
        
        # Chercher la couleur du mesh
        fc = [0.7, 0.65, 0.6]
        ec = '#5a5040'
        
        z_vals = verts[:, 2]
        if max(z_vals) > 2.5:
            fc = [0.71, 0.24, 0.20]  # toit rouge
            ec = '#8b2020'
        elif min(z_vals) > 0 and max(z_vals) < 2.5:
            fc = [0.82, 0.74, 0.68]
            ec = '#6b5b45'
        
        poly.set_facecolor(fc)
        poly.set_edgecolor(ec)
        poly.set_linewidth(0.3)
        ax.add_collection3d(poly)
    
    all_verts = mesh.vertices
    ax.set_xlim(all_verts[:,0].min()-1, all_verts[:,0].max()+1)
    ax.set_ylim(all_verts[:,1].min()-1, all_verts[:,1].max()+1)
    ax.set_zlim(0, all_verts[:,2].max()+1)
    ax.set_xlabel("X (m)", color='white')
    ax.set_ylabel("Y (m)", color='white')
    ax.set_zlabel("Z (m)", color='white')
    ax.tick_params(colors='white')
    ax.view_init(elev=25, azim=-55)
    ax.set_title("Vue 3D — Maison", color='white', fontsize=13, fontweight='bold')
    
    # Vue de dessus
    ax2 = fig.add_subplot(132)
    ax2.set_facecolor('#16213e')
    for face in mesh.faces:
        verts = mesh.vertices[face]
        x, y, z = verts[:,0], verts[:,1], verts[:,2]
        if np.mean(z) > 2.5:
            ax2.fill(x, y, alpha=0.5, facecolor='#b43c32', edgecolor='#8b2020', linewidth=0.3)
        elif np.mean(z) < 0.1:
            ax2.fill(x, y, alpha=0.3, facecolor='#c3b9af', edgecolor='#a09080', linewidth=0.3)
        else:
            ax2.fill(x, y, alpha=0.4, facecolor='#c8b89a', edgecolor='#8b7355', linewidth=0.3)
    
    ax2.set_aspect('equal')
    ax2.set_xlabel("X (m)", color='white')
    ax2.set_ylabel("Y (m)", color='white')
    ax2.tick_params(colors='white')
    ax2.grid(True, alpha=0.2, color='white')
    ax2.set_title("Vue de dessus (Plan)", color='white', fontsize=13, fontweight='bold')
    
    # Infos
    ax3 = fig.add_subplot(133)
    ax3.set_facecolor('#16213e')
    ax3.axis('off')
    
    info_text = "🏗️  ARCHIPLAN 3D v1.0\n\n"
    info_text += f"Sommets : {len(mesh.vertices):,}\n"
    info_text += f"Faces   : {len(mesh.faces):,}\n\n"
    
    if metadata:
        info_text += f"Murs extérieurs : {len(metadata.get('walls', []))}\n"
        info_text += f"Portes : {len(metadata.get('doors', []))}\n"
        info_text += f"Fenêtres : {len(metadata.get('windows', []))}\n"
        if 'roof' in metadata:
            info_text += f"Toit : {metadata['roof']['type']}\n"
    
    info_text += "\n📐 Échelle : 1m = 50px\n"
    info_text += "📏 Hauteur murs : 2.70m\n"
    info_text += "🏠 Hauteur toit : +1.50m\n"
    
    ax3.text(0.05, 0.95, info_text, transform=ax3.transAxes,
             fontfamily='monospace', fontsize=11, color='white',
             verticalalignment='top')
    
    plt.tight_layout()
    path = str(OUT_DIR / "maison_3d_preview.png")
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    
    print(f"✅ Rendu → {path}")
    return path


# ============================================================
#  ÉTAPE 5 : VIEWER WEB INTERACTIF (Three.js)
# ============================================================

def generate_web_viewer(mesh, metadata: dict = None) -> str:
    """Génère un viewer 3D interactif HTML avec Three.js."""
    
    # Extraire les données géométriques
    verts = mesh.vertices.tolist()
    faces = mesh.faces.tolist()
    
    # Construire le JSON des données
    scene_data = {
        "vertices": verts,
        "faces": faces,
        "metadata": metadata or {},
    }
    
    html = '''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ArchiPlan 3D — Viewer Interactif</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #1a1a2e; font-family: 'Segoe UI', sans-serif; overflow: hidden; }
#info {
  position: absolute; top: 20px; left: 20px;
  background: rgba(0,0,0,0.7); color: white; padding: 15px 20px;
  border-radius: 10px; backdrop-filter: blur(10px);
  font-size: 14px; z-index: 10;
}
#info h1 { font-size: 22px; margin-bottom: 8px; }
#info .stat { color: #aaa; font-size: 12px; }
#controls {
  position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%);
  background: rgba(0,0,0,0.7); padding: 10px 20px; border-radius: 25px;
  display: flex; gap: 10px; z-index: 10;
}
#controls button {
  background: #e94560; color: white; border: none; padding: 8px 16px;
  border-radius: 20px; cursor: pointer; font-size: 13px; transition: 0.2s;
}
#controls button:hover { background: #ff6b81; }
#controls button.active { background: #0f3460; }
canvas { display: block; }
</style>
</head>
<body>

<div id="info">
  <h1>🏗️ ArchiPlan 3D v1.0</h1>
  <div id="stats" class="stat">Chargement...</div>
</div>

<div id="controls">
  <button onclick="setView('perspective')" class="active">🎥 3D</button>
  <button onclick="setView('top')">📐 Dessus</button>
  <button onclick="setView('front')">👁️ Face</button>
  <button onclick="setView('side')">👈 Côté</button>
  <button onclick="toggleWireframe()">🔲 Filaire</button>
  <button onclick="toggleAutoRotate()">🔄 Auto</button>
</div>

<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
  }
}
</script>

<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const sceneData = ''' + json.dumps(scene_data) + ''';

// Scene
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a2e);
scene.fog = new THREE.Fog(0x1a1a2e, 20, 50);

// Camera
const camera = new THREE.PerspectiveCamera(55, window.innerWidth/window.innerHeight, 0.5, 100);
camera.position.set(12, 9, 14);

// Renderer
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
document.body.appendChild(renderer.domElement);

// Controls
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(7, 1.5, 5);
controls.autoRotate = true;
controls.autoRotateSpeed = 0.3;
controls.maxPolarAngle = Math.PI / 2.2;

// Lights
const ambient = new THREE.AmbientLight(0x404060, 1.0);
scene.add(ambient);

const sun = new THREE.DirectionalLight(0xffeedd, 4.0);
sun.position.set(15, 20, 10);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
sun.shadow.camera.near = 0.5;
sun.shadow.camera.far = 50;
sun.shadow.camera.left = -20;
sun.shadow.camera.right = 20;
sun.shadow.camera.top = 20;
sun.shadow.camera.bottom = -20;
scene.add(sun);

const fill = new THREE.DirectionalLight(0xaaccff, 1.5);
fill.position.set(-5, 2, -5);
scene.add(fill);

// Ground
const groundGeo = new THREE.PlaneGeometry(30, 30);
const groundMat = new THREE.MeshStandardMaterial({ color: 0x2a2a3e, roughness: 0.9 });
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.01;
ground.receiveShadow = true;
scene.add(ground);

// Grid
const grid = new THREE.GridHelper(25, 25, 0x444466, 0x222244);
grid.position.y = 0;
scene.add(grid);

// Build mesh from scene data
const geometry = new THREE.BufferGeometry();
const vertices = new Float32Array(sceneData.vertices.flat());
const indices = new Uint32Array(sceneData.faces.flat());

geometry.setIndex(new THREE.BufferAttribute(indices, 1));
geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
geometry.computeVertexNormals();

// Color by height for walls/roof
const colors = new Float32Array(vertices.length);
const wallMat = new THREE.MeshStandardMaterial({
  vertexColors: true,
  roughness: 0.7,
  metalness: 0.05,
});

for (let i = 0; i < vertices.length; i += 3) {
  const z = vertices[i + 2];
  if (z < 0.05) {
    // Floor
    colors[i] = 0.76; colors[i+1] = 0.73; colors[i+2] = 0.69;
  } else if (z > 2.6) {
    // Roof
    colors[i] = 0.73; colors[i+1] = 0.24; colors[i+2] = 0.20;
  } else {
    // Walls
    colors[i] = 0.82; colors[i+1] = 0.74; colors[i+2] = 0.68;
  }
}
geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

const house = new THREE.Mesh(geometry, wallMat);
house.castShadow = true;
house.receiveShadow = true;
scene.add(house);

// Wireframe
const wireframeMat = new THREE.MeshBasicMaterial({
  color: 0x8899aa,
  wireframe: true,
  transparent: true,
  opacity: 0.15,
});
const wireframe = new THREE.Mesh(geometry, wireframeMat);
wireframe.visible = false;
wireframe.position.copy(house.position);
scene.add(wireframe);

// Stats
document.getElementById('stats').innerHTML = `
  Sommets: ${sceneData.vertices.length.toLocaleString()} |
  Faces: ${sceneData.faces.length.toLocaleString()} |
  ${sceneData.metadata.roof ? 'Toit: 2 pentes | ' : ''}
  Murs: ${sceneData.metadata.walls?.length || '?'}
`;

// Controls
window.setView = (view) => {
  document.querySelectorAll('#controls button').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  
  const target = new THREE.Vector3(7, 1.5, 5);
  controls.target.copy(target);
  
  switch(view) {
    case 'top':
      camera.position.set(target.x, target.y + 12, target.z + 0.1);
      controls.update();
      break;
    case 'front':
      camera.position.set(target.x, target.y + 1.5, target.z - 10);
      controls.update();
      break;
    case 'side':
      camera.position.set(target.x + 10, target.y + 1.5, target.z);
      controls.update();
      break;
    default:
      camera.position.set(12, 9, 14);
      controls.target.set(7, 1.5, 5);
      controls.update();
  }
};

window.toggleWireframe = () => {
  wireframe.visible = !wireframe.visible;
  event.target.classList.toggle('active');
};

window.toggleAutoRotate = () => {
  controls.autoRotate = !controls.autoRotate;
  event.target.classList.toggle('active');
};

// Animation loop
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
animate();

// Resize
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
</script>
</body>
</html>'''

    path = str(OUT_DIR / "viewer_3d.html")
    Path(path).write_text(html)
    print(f"✅ Viewer Web → {path}")
    return path


# ============================================================
#  ÉTAPE 6 : SCRIPT BLENDER COMPLET
# ============================================================

def generate_blender_script(walls: dict) -> str:
    """Génère un script Blender complet avec textures et rendu."""
    wall_h = walls["wall_height"]
    wall_t = walls["wall_thickness"]
    W, H = walls["image_size"]
    scale = 1.0 / 50.0
    
    script = f'''"""Script Blender — ArchiPlan 3D v1.0 — Généré automatiquement"""
import bpy, math

# Nettoyer
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# ─── Matériaux ──────────────────────────────────────────────────────
def make_material(name, color, roughness=0.5):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat

brique = make_material("Brique", (0.82, 0.70, 0.55), 0.7)
crepi = make_material("Crepi", (0.92, 0.88, 0.84), 0.6)
tuile = make_material("Tuile", (0.71, 0.24, 0.20), 0.4)
bois = make_material("Bois", (0.55, 0.35, 0.20), 0.5)
verre = make_material("Verre", (0.82, 0.92, 0.98), 0.1)
sol_mat = make_material("Sol", (0.76, 0.73, 0.69), 0.8)

# ─── Fonctions ──────────────────────────────────────────────────────
def create_wall(x1, y1, x2, y2, height={wall_h}, thickness={wall_t}, mat=brique):
    dx, dy = x2 - x1, y2 - y1
    length = math.sqrt(dx*dx + dy*dy)
    if length < 0.001: return None
    angle = math.atan2(dy, dx)
    cx, cy = (x1+x2)/2, (y1+y2)/2
    bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, height/2))
    obj = bpy.context.active_object
    obj.scale = (length, thickness, height)
    obj.rotation_euler.z = angle
    obj.data.materials.append(mat)
    return obj

def create_roof(width, depth, wall_height):
    h = wall_height + 0.2
    peak = wall_height + 1.5
    mid = width/2
    verts = [(0,0,h), (width,0,h), (width,depth,h), (0,depth,h),
             (mid,0,peak), (mid,depth,peak)]
    faces = [(0,1,4), (0,4,5), (0,5,3), (1,2,5), (1,5,4), (2,3,5)]
    mesh = bpy.data.meshes.new("Toit")
    obj = bpy.data.objects.new("Toit", mesh)
    bpy.context.collection.objects.link(obj)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj.data.materials.append(tuile)
    return obj

def create_door(x, y, w=0.9, h=2.1, thickness=0.1):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y-thickness/2, h/2))
    obj = bpy.context.active_object
    obj.scale = (w/2, thickness, h/2)
    obj.data.materials.append(bois)
    return obj

def create_window(x, y, w=1.0, h=1.2, thickness=0.05):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y-thickness, 1.0+h/2))
    obj = bpy.context.active_object
    obj.scale = (w/2, thickness, h/2)
    obj.data.materials.append(verre)
    return obj

# ─── Construction ──────────────────────────────────────────────────

# Sol
bpy.ops.mesh.primitive_plane_add(size=1, location=({(W*scale)/2:.2f}, {(H*scale)/2:.2f}, 0))
sol = bpy.context.active_object
sol.scale = ({(W*scale)/2:.2f}, {(H*scale)/2:.2f}, 1)
sol.data.materials.append(sol_mat)
sol.name = "Sol"

# Murs extérieurs
'''

    for w in walls["exterior"]:
        x1, y1 = w["x1"]*scale, w["y1"]*scale
        x2, y2 = w["x2"]*scale, w["y2"]*scale
        script += f'create_wall({x1:.3f}, {y1:.3f}, {x2:.3f}, {y2:.3f}, mat=brique)\n'

    script += '\n# Murs intérieurs\n'
    for w in walls["interior"]:
        x1, y1 = w["x1"]*scale, w["y1"]*scale
        x2, y2 = w["x2"]*scale, w["y2"]*scale
        script += f'create_wall({x1:.3f}, {y1:.3f}, {x2:.3f}, {y2:.3f}, mat=crepi)\n'
    
    script += f'''
# Toit
create_roof({W*scale:.2f}, {H*scale:.2f}, {wall_h})

# Portes
create_door({W*scale*0.55:.2f}, {H*scale*0.62:.2f})
create_door({W*scale*0.32:.2f}, {H*scale*0.85:.2f})
create_door({W*scale*0.6:.2f}, {H*scale*0.30:.2f})

# Fenêtres
create_window({W*scale*0.3:.2f}, {0:.1f})
create_window({W*scale*0.78:.2f}, {0:.1f})
create_window({W*scale:.2f}, {H*scale*0.25:.2f})

# Caméra
bpy.ops.object.camera_add(location=({W*scale*0.5:.1f}, {H*scale*-0.6:.1f}, {wall_h*1.5:.1f}))
cam = bpy.context.active_object
cam.rotation_euler = (math.radians(55), 0, 0)
bpy.context.scene.camera = cam

# Éclairage
bpy.ops.object.light_add(type='SUN', location=({W*scale*0.3:.1f}, {H*scale*-0.4:.1f}, {wall_h*3:.1f}))
sun = bpy.context.active_object
sun.data.energy = 5

# Paramètres de rendu
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.render.resolution_x = 1920
bpy.context.scene.render.resolution_y = 1080
bpy.context.scene.render.filepath = "/tmp/rendu_maison.png"

print("\\n✅ Maison 3D construite !")
print("   Lancez le rendu : F12")
print("   Ou script : bpy.ops.render.render(write_still=True)")
'''

    path = str(OUT_DIR / "maison_blender.py")
    Path(path).write_text(script)
    print(f"✅ Script Blender → {path}")
    return path


# ============================================================
#  MAIN — PIPELINE COMPLET
# ============================================================

def run_full_pipeline(image_path: str = None):
    """Exécute le pipeline complet ArchiPlan 3D v1.0."""
    print("=" * 60)
    print("🏗️  ARCHIPLAN 3D — Pipeline Complet v1.0")
    print("=" * 60)
    
    # 1. Plan 2D
    print("\n📄 ÉTAPE 1/6 : Plan 2D")
    if image_path and Path(image_path).exists():
        plan_path = image_path
        walls = analyze_floor_plan(plan_path)  # Analyse IA pour image réelle
    else:
        plan_path, walls = create_sample_floor_plan()  # Plan démo + données structurées
        print(f"   ✅ {len(walls['rooms'])} pièces, {len(walls['interior'])} murs intérieurs")
    
    # 2. Analyse IA (seulement si image réelle)
    if image_path and Path(image_path).exists():
        print("\n🔍 ÉTAPE 2/6 : Analyse IA")
        walls = analyze_floor_plan(plan_path)
    else:
        print("\n🔍 ÉTAPE 2/6 : Analyse IA (skip - plan structuré)")
    
    # 3. Modèle 3D
    print("\n🧊 ÉTAPE 3/6 : Construction 3D")
    mesh, obj_path, metadata = build_3d_model(walls)
    
    # 4. Rendu
    print("\n📸 ÉTAPE 4/6 : Rendu preview")
    preview_path = render_preview(mesh, metadata)
    
    # 5. Viewer Web
    print("\n🌐 ÉTAPE 5/6 : Viewer Web interactif")
    viewer_path = generate_web_viewer(mesh, metadata)
    
    # 6. Script Blender
    print("\n🎬 ÉTAPE 6/6 : Script Blender")
    blender_path = generate_blender_script(walls)
    
    print("\n" + "=" * 60)
    print("✅ PIPELINE TERMINÉ — Fichiers produits :")
    print(f"   📄 Plan 2D       : {plan_path}")
    print(f"   🔍 Détection     : {OUT_DIR}/detection_vis.png")
    print(f"   🧊 Modèle 3D     : {obj_path}")
    print(f"   📸 Rendu preview : {preview_path}")
    print(f"   🌐 Viewer Web    : {viewer_path}")
    print(f"   🎬 Blender       : {blender_path}")
    print(f"   💾 Métadonnées   : {OUT_DIR}/metadata.json")
    print("=" * 60)
    
    return {
        "plan": plan_path,
        "detection": str(OUT_DIR / "detection_vis.png"),
        "model": obj_path,
        "preview": preview_path,
        "viewer": viewer_path,
        "blender": blender_path,
    }


if __name__ == "__main__":
    import sys
    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    run_full_pipeline(image_path)
