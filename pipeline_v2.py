#!/usr/bin/env python3
"""
ARCHIPLAN 3D — Rendu Architectural Professionnel
Maison réaliste : murs épais, toit avec débords, fondations, ouvertures encadrées
"""
import trimesh
import numpy as np
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path("/tmp/archiplan3d_output")
OUT_DIR.mkdir(exist_ok=True)

# ============================================================
# MAISON RÉALISTE — DIMENSIONS ARCHITECTURALES
# ============================================================

# Dimensions en mètres (maison standard)
HOUSE_W = 11.0   # largeur
HOUSE_D = 8.5    # profondeur
WALL_H = 2.70    # hauteur sous plafond
WALL_T = 0.20    # épaisseur des murs
ROOF_H = 2.0     # hauteur du toit (pente)
ROOF_OVERHANG = 0.60  # débord de toit
FOUNDATION_H = 0.30   # hauteur des fondations
DOOR_W = 0.90    # largeur porte
DOOR_H = 2.10    # hauteur porte
WINDOW_W = 1.20  # largeur fenêtre
WINDOW_H = 1.10  # hauteur fenêtre
WINDOW_SILL = 0.90  # hauteur allège

# Pièces
ROOMS = {
    "Salon":      {"x": 0, "y": 0, "w": 4.2, "h": 4.2},
    "Cuisine":    {"x": 4.4, "y": 0, "w": 3.2, "h": 3.5},
    "Chambre 1":  {"x": 7.8, "y": 0, "w": 3.0, "h": 4.2},
    "SDB":        {"x": 0, "y": 4.4, "w": 2.2, "h": 3.9},
    "Chambre 2":  {"x": 2.4, "y": 4.4, "w": 3.6, "h": 3.9},
    "Couloir":    {"x": 6.2, "y": 4.4, "w": 1.6, "h": 3.9},
    "Bureau":     {"x": 8.0, "y": 4.4, "w": 2.8, "h": 3.9},
}

# Murs intérieurs (coordonnées absolues en mètres)
INTERIOR_WALLS = [
    (4.2, 0, 4.2, 4.2),    # vertical salon/cuisine
    (4.2, 4.4, 4.2, 8.3),  # vertical cuisine/couloir  
    (7.6, 0, 7.6, 4.2),    # vertical cuisine/chambre1
    (2.2, 4.4, 2.2, 5.9),  # vertical SDB/chambre2
    (6.0, 4.4, 6.0, 6.2),  # vertical chambre2/couloir
    (7.8, 5.9, 7.8, 8.3),  # vertical couloir/bureau
    (0, 4.2, 4.2, 4.2),    # horizontal salon/SDB
    (4.2, 3.5, 7.6, 3.5),  # horizontal cuisine/chambre1
    (2.2, 5.9, 6.0, 5.9),  # horizontal chambre2 milieu
    (0, 4.2, 6.0, 4.2),    # horizontal bas complet
]

# ============================================================
# GÉNÉRATION DU PLAN 2D RÉALISTE
# ============================================================

def create_architectural_plan():
    """Dessine un plan 2D style architecte."""
    scale = 60  # pixels par mètre
    W = int(HOUSE_W * scale) + 100
    H = int(HOUSE_D * scale) + 100
    margin = 50
    
    img = Image.new("RGB", (W, H), (252, 250, 245))
    draw = ImageDraw.Draw(img)
    
    def mx(x): return margin + x * scale
    def my(y): return margin + y * scale
    
    # Fondations
    draw.rectangle(
        [mx(-0.05), my(-0.05), mx(HOUSE_W+0.05), my(HOUSE_D+0.05)],
        fill=(230, 225, 218), outline=(180, 175, 168), width=3
    )
    
    # Murs extérieurs (épais)
    wall_color = (50, 45, 40)
    ext = [
        (mx(0), my(0), mx(HOUSE_W), my(0)),           # nord
        (mx(HOUSE_W), my(0), mx(HOUSE_W), my(HOUSE_D)), # est
        (mx(HOUSE_W), my(HOUSE_D), mx(0), my(HOUSE_D)), # sud
        (mx(0), my(HOUSE_D), mx(0), my(0)),            # ouest
    ]
    for x1, y1, x2, y2 in ext:
        draw.line([(x1, y1), (x2, y2)], fill=wall_color, width=int(WALL_T*scale))
    
    # Murs intérieurs
    int_color = (100, 95, 90)
    for x1, y1, x2, y2 in INTERIOR_WALLS:
        draw.line([(mx(x1), my(y1)), (mx(x2), my(y2))], fill=int_color, width=int(WALL_T*scale*0.8))
    
    # Portes (arc)
    doors = [
        (mx(4.2), my(1.5), "h"),   # salon→cuisine
        (mx(6.2), my(0.05), "v"),  # cuisine→chambre1  
        (mx(1.0), my(4.2), "h"),   # salon→SDB
        (mx(3.5), my(4.4), "v"),   # SDB→chambre2
        (mx(6.2), my(5.9), "h"),   # chambre2→couloir
        (mx(7.8), my(6.8), "v"),   # couloir→bureau
    ]
    door_w = scale * 0.9
    door_t = scale * 0.1
    for cx, cy, orient in doors:
        if orient == "h":
            # Porte horizontale — arc dans le mur
            draw.arc([cx-door_w/2, cy-door_w/2.5, cx+door_w/2, cy+door_w/2.5],
                     start=0, end=180, fill=(180, 160, 130), width=3)
            draw.line([(cx-door_w/2, cy), (cx+door_w/2, cy)], fill=(180, 160, 130), width=4)
        else:
            draw.arc([cx-door_w/2.5, cy-door_w/2, cx+door_w/2.5, cy+door_w/2],
                     start=90, end=270, fill=(180, 160, 130), width=3)
            draw.line([(cx, cy-door_w/2), (cx, cy+door_w/2)], fill=(180, 160, 130), width=4)
    
    # Fenêtres
    windows = [
        (mx(2.0), my(-0.05), 1.5),    # salon nord
        (mx(5.5), my(-0.05), 1.2),    # cuisine nord
        (mx(8.8), my(-0.05), 1.0),    # chambre1 nord
        (mx(HOUSE_W+0.05), my(2.0), 1.0, "v"),  # chambre1 est
        (mx(-0.05), my(1.5), 1.2, "v"),          # salon ouest
        (mx(-0.05), my(5.5), 1.0, "v"),          # chambre2 ouest
        (mx(1.0), my(HOUSE_D+0.05), 1.2),        # SDB sud
        (mx(4.0), my(HOUSE_D+0.05), 1.2),        # chambre2 sud
        (mx(7.0), my(HOUSE_D+0.05), 1.0),        # couloir sud
    ]
    
    win_color = (135, 190, 240)
    win_frame = (70, 130, 180)
    for w in windows:
        if len(w) == 4 and w[3] == "v":
            cx, cy, wh = w[0], w[1], w[2]
            hw = wh * scale
            hh = scale * 0.15
            draw.rectangle([cx-hh/2, cy-hw/2, cx+hh/2, cy+hw/2], fill=win_color, outline=win_frame, width=2)
        else:
            cx, cy, ww = w[0], w[1], w[2]
            hw = ww * scale
            hh = scale * 0.15
            draw.rectangle([cx-hw/2, cy-hh/2, cx+hw/2, cy+hh/2], fill=win_color, outline=win_frame, width=2)
    
    # Étiquettes
    try:
        font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", 18)
        font_sm = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 14)
    except:
        font = ImageFont.load_default()
        font_sm = font
    
    for name, room in ROOMS.items():
        cx = mx(room["x"] + room["w"]/2)
        cy = my(room["y"] + room["h"]/2)
        area = room["w"] * room["h"]
        label = f"{name}\n{area:.1f} m²"
        bbox = draw.textbbox((0, 0), label, font=font_sm)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw/2, cy - th/2), label, fill=(120, 115, 110), font=font_sm,
                 align="center")
    
    # Cotation extérieure
    dash_color = (150, 145, 140)
    for side in ["nord", "est"]:
        draw.line([(mx(0), my(-0.35)), (mx(HOUSE_W), my(-0.35))], fill=dash_color, width=1)
        draw.line([(mx(-0.05), my(-0.4)), (mx(-0.05), my(-0.25))], fill=dash_color, width=2)
        draw.line([(mx(HOUSE_W+0.05), my(-0.4)), (mx(HOUSE_W+0.05), my(-0.25))], fill=dash_color, width=2)
    draw.text((mx(HOUSE_W/2)-30, my(-0.65)), f"{HOUSE_W:.1f} m", fill=(130, 125, 120), font=font)
    
    # Échelle
    scale_bar_y = H - 25
    draw.line([(margin, scale_bar_y), (margin + 100, scale_bar_y)], fill=(60, 55, 50), width=3)
    draw.line([(margin, scale_bar_y-5), (margin, scale_bar_y+5)], fill=(60, 55, 50), width=2)
    draw.line([(margin+100, scale_bar_y-5), (margin+100, scale_bar_y+5)], fill=(60, 55, 50), width=2)
    draw.text((margin+30, scale_bar_y-16), "1 m", fill=(80, 75, 70), font=font_sm)
    
    path = str(OUT_DIR / "plan_2d.png")
    img.save(path)
    print(f"✅ Plan architectural → {path}")
    return path


# ============================================================
# MODÈLE 3D — CONSTRUCTION ARCHITECTURALE
# ============================================================

def create_wall_mesh(x1, y1, z1, x2, y2, z2, thickness, color):
    """Crée un mur 3D avec épaisseur."""
    dx, dy = x2 - x1, y2 - y1
    length = np.sqrt(dx*dx + dy*dy)
    if length < 0.01:
        return None
    
    nx = -dy / length * thickness / 2
    ny = dx / length * thickness / 2
    
    vertices = np.array([
        [x1+nx, y1+ny, z1], [x1-nx, y1-ny, z1],
        [x2-nx, y2-ny, z1], [x2+nx, y2+ny, z1],
        [x1+nx, y1+ny, z2], [x1-nx, y1-ny, z2],
        [x2-nx, y2-ny, z2], [x2+nx, y2+ny, z2],
    ])
    
    faces = np.array([
        [0,1,2],[0,2,3], [4,5,6],[4,6,7],
        [0,4,7],[0,7,3], [1,5,6],[1,6,2],
        [0,1,5],[0,5,4], [3,2,6],[3,6,7],
    ])
    
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.visual.face_colors = [color] * len(faces)
    return mesh


def build_architectural_3d():
    """Construit le modèle 3D architectural complet."""
    meshes = []
    
    # --- FONDATIONS ---
    foundation_z = FOUNDATION_H
    foundation_color = [140, 130, 120, 255]
    
    # Dalle
    slab_verts = np.array([
        [-0.10, -0.10, 0], [HOUSE_W+0.10, -0.10, 0],
        [HOUSE_W+0.10, HOUSE_D+0.10, 0], [-0.10, HOUSE_D+0.10, 0],
        [-0.10, -0.10, foundation_z], [HOUSE_W+0.10, -0.10, foundation_z],
        [HOUSE_W+0.10, HOUSE_D+0.10, foundation_z], [-0.10, HOUSE_D+0.10, foundation_z],
    ])
    slab_faces = np.array([
        [0,1,2],[0,2,3], [4,5,6],[4,6,7],
        [0,4,7],[0,7,3], [1,5,6],[1,6,2],
        [0,1,5],[0,5,4], [3,2,6],[3,6,7],
    ])
    foundation = trimesh.Trimesh(vertices=slab_verts, faces=slab_faces)
    foundation.visual.face_colors = [foundation_color] * len(slab_faces)
    meshes.append(foundation)
    
    # --- MURS EXTÉRIEURS ---
    wall_color = [210, 195, 175, 255]  # crépi beige
    ext_walls = [
        (0, 0, HOUSE_W, 0),           # nord
        (HOUSE_W, 0, HOUSE_W, HOUSE_D), # est
        (HOUSE_W, HOUSE_D, 0, HOUSE_D), # sud
        (0, HOUSE_D, 0, 0),            # ouest
    ]
    for x1, y1, x2, y2 in ext_walls:
        m = create_wall_mesh(x1, y1, foundation_z, x2, y2, foundation_z + WALL_H,
                            WALL_T, wall_color)
        if m:
            meshes.append(m)
    
    # --- MURS INTÉRIEURS ---
    int_color = [225, 218, 208, 255]  # blanc cassé
    for x1, y1, x2, y2 in INTERIOR_WALLS:
        m = create_wall_mesh(x1, y1, foundation_z, x2, y2, foundation_z + WALL_H,
                            WALL_T * 0.7, int_color)
        if m:
            meshes.append(m)
    
    # --- TOIT À 2 PENTES AVEC DÉBORDS ---
    overhang = ROOF_OVERHANG
    ridge_h = foundation_z + WALL_H + ROOF_H
    eaves_h = foundation_z + WALL_H
    
    # Faîtage au milieu
    ridge_x = HOUSE_W / 2
    
    roof_color = [170, 55, 45, 255]  # tuile terre cuite
    
    # Pan nord (pente descend vers le nord)
    roof_n_verts = np.array([
        [-overhang, -overhang, eaves_h],
        [HOUSE_W + overhang, -overhang, eaves_h],
        [ridge_x, -overhang, ridge_h],
        [-overhang, HOUSE_D + overhang, eaves_h],
        [HOUSE_W + overhang, HOUSE_D + overhang, eaves_h],
        [ridge_x, HOUSE_D + overhang, ridge_h],
    ])
    roof_n_faces = np.array([
        [0,2,1], [0,3,5], [0,5,2], [1,2,5], [1,5,4], [0,1,4], [0,4,3],
    ])
    roof_n = trimesh.Trimesh(vertices=roof_n_verts, faces=roof_n_faces)
    roof_n.visual.face_colors = [roof_color] * len(roof_n_faces)
    meshes.append(roof_n)
    
    # Pan sud (pente descend vers le sud)
    roof_s_verts = np.array([
        [-overhang, -overhang, eaves_h],
        [HOUSE_W + overhang, -overhang, eaves_h],
        [ridge_x, -overhang, ridge_h],
        [-overhang, HOUSE_D + overhang, eaves_h],
        [HOUSE_W + overhang, HOUSE_D + overhang, eaves_h],
        [ridge_x, HOUSE_D + overhang, ridge_h],
    ])
    roof_s_faces = np.array([
        [3,5,4], [0,3,5], [0,5,2], [1,2,5], [1,5,4], [0,1,4], [0,4,3],
    ])
    roof_s = trimesh.Trimesh(vertices=roof_s_verts, faces=roof_s_faces)
    roof_s.visual.face_colors = [roof_color] * len(roof_s_faces)
    meshes.append(roof_s)
    
    # --- PLANCHER (sol intérieur) ---
    floor_color = [180, 165, 145, 255]
    floor_verts = np.array([
        [0, 0, foundation_z], [HOUSE_W, 0, foundation_z],
        [HOUSE_W, HOUSE_D, foundation_z], [0, HOUSE_D, foundation_z],
    ])
    floor_faces = np.array([[0,1,2],[0,2,3]])
    floor = trimesh.Trimesh(vertices=floor_verts, faces=floor_faces)
    floor.visual.face_colors = [floor_color, floor_color]
    meshes.append(floor)
    
    # --- PORTES ---
    door_color = [130, 95, 60, 255]   # bois foncé
    frame_color = [160, 140, 120, 255] # cadre
    door_z = foundation_z
    
    door_positions = [
        (4.2, 1.8, "v"),   # salon→cuisine
        (2.65, 0.01, "h"), # cuisine→chambre1  (ajusté)
        (1.1, 4.2, "v"),   # salon→SDB
        (3.5, 4.4, "h"),   # SDB→chambre2
        (6.2, 5.9, "h"),   # chambre2→couloir
        (7.8, 6.8, "v"),   # couloir→bureau
    ]
    
    for cx, cy, orient in door_positions:
        if orient == "h":
            m = create_wall_mesh(cx-DOOR_W/2, cy, door_z, cx+DOOR_W/2, cy,
                                door_z+DOOR_H, WALL_T*0.4, door_color)
        else:
            m = create_wall_mesh(cx, cy-DOOR_W/2, door_z, cx, cy+DOOR_W/2,
                                door_z+DOOR_H, WALL_T*0.4, door_color)
        if m:
            meshes.append(m)
    
    # --- FENÊTRES ---
    glass_color = [160, 200, 235, 180]  # verre semi-transparent
    win_z = foundation_z + WINDOW_SILL
    
    window_positions = [
        (2.0, -0.03, WINDOW_W, "h"),     # salon nord
        (5.5, -0.03, 1.2, "h"),          # cuisine nord
        (8.8, -0.03, 1.0, "h"),          # chambre1 nord
        (HOUSE_W+0.03, 2.0, 1.0, "v"),   # chambre1 est
        (-0.03, 1.5, 1.2, "v"),          # salon ouest
        (-0.03, 5.5, 1.0, "v"),          # chambre2 ouest
        (1.0, HOUSE_D+0.03, 1.2, "h"),   # SDB sud
        (4.0, HOUSE_D+0.03, 1.2, "h"),   # chambre2 sud
        (7.0, HOUSE_D+0.03, 1.0, "h"),   # couloir sud
    ]
    
    for cx, cy, ww, orient in window_positions:
        if orient == "h":
            m = create_wall_mesh(cx-ww/2, cy, win_z, cx+ww/2, cy,
                                win_z+WINDOW_H, WALL_T*0.3, glass_color)
        else:
            m = create_wall_mesh(cx, cy-ww/2, win_z, cx, cy+ww/2,
                                win_z+WINDOW_H, WALL_T*0.3, glass_color)
        if m:
            meshes.append(m)
    
    # --- ASSEMBLAGE ---
    combined = trimesh.util.concatenate(meshes)
    obj_path = str(OUT_DIR / "maison_3d.obj")
    combined.export(obj_path)
    
    print(f"\n✅ Modèle 3D architectural → {obj_path}")
    print(f"   • {len(meshes)} composants")
    print(f"   • {len(combined.vertices):,} sommets")
    print(f"   • {len(combined.faces):,} faces")
    print(f"   • 7 pièces : {', '.join(ROOMS.keys())}")
    print(f"   • Dimensions : {HOUSE_W:.1f}m × {HOUSE_D:.1f}m")
    print(f"   • Surface : {HOUSE_W*HOUSE_D:.1f} m²")
    print(f"   • Hauteur : {foundation_z+WALL_H+ROOF_H:.1f}m (fondations+{WALL_H}m+toit)")
    
    # Metadata
    metadata = {
        "dimensions": f"{HOUSE_W:.1f}m × {HOUSE_D:.1f}m",
        "surface": f"{HOUSE_W*HOUSE_D:.1f} m²",
        "hauteur": f"{foundation_z+WALL_H+ROOF_H:.1f}m",
        "pieces": [{name: f"{r['w']*r['h']:.1f} m²"} for name, r in ROOMS.items()],
        "composants": len(meshes),
        "sommets": len(combined.vertices),
        "faces": len(combined.faces),
    }
    with open(OUT_DIR / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    return combined, obj_path, metadata


# ============================================================
# RENDU 3D — VUES ARCHITECTURALES
# ============================================================

def render_architectural_views(mesh, metadata):
    """Rendu 3D professionnel avec vues multiples."""
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    
    fig = plt.figure(figsize=(20, 14), facecolor='#f5f0eb')
    
    # === VUE 1 : Perspective 3D (grande) ===
    ax = fig.add_subplot(221, projection='3d')
    ax.set_facecolor('#e8e2d8')
    
    for face in mesh.faces:
        verts = mesh.vertices[face]
        poly = Poly3DCollection([verts], alpha=0.92)
        
        z_vals = verts[:, 2]
        z_max, z_min = max(z_vals), min(z_vals)
        
        if z_max > WALL_H + 0.5:
            poly.set_facecolor('#a83a2a')  # toit tuile
            poly.set_edgecolor('#6b2018')
        elif z_max < FOUNDATION_H + 0.1:
            poly.set_facecolor('#beb5a8')  # fondations
            poly.set_edgecolor('#9e9588')
        elif z_min > WALL_H * 0.7 and z_max < WALL_H + FOUNDATION_H + 0.1:
            poly.set_facecolor('#e8ddd0')  # murs
            poly.set_edgecolor('#c4b8a8')
        elif 0.4 < z_max < 2.5:
            if verts.shape[0] <= 4:  # probablement une porte/fenêtre
                if any(v < 0.85 for v in [z_max - z_min]):
                    poly.set_facecolor('#8b6b4a')  # porte
                else:
                    poly.set_facecolor('#b8d8f0')  # fenêtre
            else:
                poly.set_facecolor('#d4ccbe')  # sol
        else:
            poly.set_facecolor('#d9d0c2')
        
        poly.set_linewidth(0.15)
        ax.add_collection3d(poly)
    
    all_v = mesh.vertices
    ax.set_xlim(all_v[:,0].min()-0.5, all_v[:,0].max()+0.5)
    ax.set_ylim(all_v[:,1].min()-0.5, all_v[:,1].max()+0.5)
    ax.set_zlim(0, all_v[:,2].max()+0.5)
    ax.set_xlabel("Largeur (m)", fontsize=9)
    ax.set_ylabel("Profondeur (m)", fontsize=9)
    ax.set_zlabel("Hauteur (m)", fontsize=9)
    ax.view_init(elev=28, azim=-50)
    ax.set_title("Perspective 3D", fontsize=13, fontweight='bold', pad=15)
    
    # === VUE 2 : Vue de dessus (plan) ===
    ax2 = fig.add_subplot(222)
    ax2.set_facecolor('#faf8f5')
    
    for face in mesh.faces:
        verts = mesh.vertices[face]
        x, y, z = verts[:,0], verts[:,1], verts[:,2]
        z_avg = np.mean(z)
        
        if z_avg > WALL_H + 0.5:
            ax2.fill(x, y, alpha=0.5, facecolor='#c44a3a', edgecolor='#8b3025', linewidth=0.2)
        elif z_avg < FOUNDATION_H + 0.1:
            ax2.fill(x, y, alpha=0.3, facecolor='#c8c0b5', edgecolor='#a09888', linewidth=0.2)
        elif FOUNDATION_H < z_avg < FOUNDATION_H + 0.05:
            ax2.fill(x, y, alpha=0.4, facecolor='#d4ccbe', edgecolor='#bfb5a5', linewidth=0.2)
        elif WALL_H*0.3 < z_avg < WALL_H*1.2:
            ax2.fill(x, y, alpha=0.5, facecolor='#e0d8cc', edgecolor='#c0b5a5', linewidth=0.2)
    
    ax2.set_aspect('equal')
    ax2.grid(True, alpha=0.2, color='#999')
    ax2.set_xlabel("Largeur (m)", fontsize=9)
    ax2.set_ylabel("Profondeur (m)", fontsize=9)
    ax2.set_title("Plan (Vue de dessus)", fontsize=13, fontweight='bold')
    
    # === VUE 3 : Façade avant ===
    ax3 = fig.add_subplot(223)
    ax3.set_facecolor('#faf8f5')
    
    for face in mesh.faces:
        verts = mesh.vertices[face]
        x, y, z = verts[:,0], verts[:,1], verts[:,2]
        if np.mean(y) > -0.2:
            ax3.fill(x, z, alpha=0.7, facecolor='#e0d8cc', edgecolor='#b8a898', linewidth=0.2)
    
    for face in mesh.faces:
        verts = mesh.vertices[face]
        x, y, z = verts[:,0], verts[:,1], verts[:,2]
        z_max = max(z)
        if z_max > WALL_H + 0.5 and np.mean(y) > -0.2:
            ax3.fill(x, z, alpha=0.7, facecolor='#c44a3a', edgecolor='#8b3025', linewidth=0.2)
    
    ax3.set_aspect('equal')
    ax3.set_xlim(0, HOUSE_W)
    ax3.set_ylim(0, FOUNDATION_H + WALL_H + ROOF_H)
    ax3.grid(True, alpha=0.15, color='#999')
    ax3.set_xlabel("Largeur (m)", fontsize=9)
    ax3.set_ylabel("Hauteur (m)", fontsize=9)
    ax3.set_title("Façade avant (Nord)", fontsize=13, fontweight='bold')
    
    # === VUE 4 : Infos ===
    ax4 = fig.add_subplot(224)
    ax4.set_facecolor('#faf8f5')
    ax4.axis('off')
    
    info = f"""ARCHIPLAN 3D — Maison Résidentielle
    
    📐 DIMENSIONS
    ──────────────────────────
    Largeur         : {HOUSE_W:.1f} m
    Profondeur      : {HOUSE_D:.1f} m
    Surface totale  : {HOUSE_W*HOUSE_D:.1f} m²
    Hauteur         : {FOUNDATION_H+WALL_H+ROOF_H:.1f} m
    Murs            : {WALL_H:.1f} m sous plafond
    Toit            : {ROOF_H:.1f} m (2 pentes)
    Fondations      : {FOUNDATION_H:.1f} m
    
    🏠 PIÈCES
    ──────────────────────────"""
    for name, r in ROOMS.items():
        area = r["w"] * r["h"]
        info += f"\n    {name:<12} {area:>5.1f} m²"
    
    info += f"""
    
    🔢 TECHNIQUE
    ──────────────────────────
    Composants      : {len(mesh.faces):,}
    Sommets         : {len(mesh.vertices):,}
    
    🚪 6 portes  •  🪟  9 fenêtres
    🧱 Murs crépi beige  •  🏠 Toit tuile
    """
    
    ax4.text(0.05, 0.98, info, transform=ax4.transAxes,
             fontfamily='monospace', fontsize=8.5, color='#3a3028',
             verticalalignment='top', linespacing=1.4)
    
    plt.tight_layout(pad=2)
    path = str(OUT_DIR / "maison_3d_preview.png")
    plt.savefig(path, dpi=200, bbox_inches='tight', facecolor='#f5f0eb')
    plt.close()
    print(f"✅ Rendu architectural → {path}")
    return path


# ============================================================
# VIEWER WEB — THREE.JS AMÉLIORÉ
# ============================================================

def generate_web_viewer(mesh, metadata):
    """Viewer 3D interactif avec ombres et textures."""
    
    scene_data = {
        "vertices": mesh.vertices.tolist(),
        "faces": mesh.faces.tolist(),
    }
    
    html = '''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ArchiPlan 3D — Maison Résidentielle</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #1a1a2e; font-family: 'Segoe UI', system-ui, sans-serif; overflow: hidden; }
#info {
  position: absolute; top: 20px; left: 20px;
  background: rgba(20,20,30,0.85); color: #e0d8cc; padding: 16px 22px;
  border-radius: 12px; backdrop-filter: blur(12px);
  font-size: 13px; z-index: 10; border: 1px solid rgba(255,255,255,0.08);
}
#info h1 { font-size: 20px; margin-bottom: 6px; color: #f0e8d8; }
#info .specs { color: #a09080; font-size: 11px; line-height: 1.6; }
#controls {
  position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%);
  background: rgba(20,20,30,0.9); padding: 10px 18px; border-radius: 30px;
  display: flex; gap: 8px; z-index: 10; border: 1px solid rgba(255,255,255,0.06);
}
#controls button {
  background: transparent; color: #c0b0a0; border: 1px solid rgba(255,255,255,0.1);
  padding: 8px 15px; border-radius: 20px; cursor: pointer; font-size: 12px;
  transition: all 0.2s; white-space: nowrap;
}
#controls button:hover { background: rgba(255,255,255,0.08); color: #f0e0d0; }
#controls button.active { background: #8b4513; color: white; border-color: #a0522d; }
#loading {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
  color: #a09080; font-size: 16px; z-index: 100;
}
</style>
</head>
<body>
<div id="loading">🏗️ Chargement...</div>
<div id="info">
  <h1>🏠 Maison Résidentielle</h1>
  <div class="specs" id="stats">7 pièces • 11×8.5m • 94m²</div>
</div>
<div id="controls">
  <button onclick="setView('persp')" class="active">🎥 3D</button>
  <button onclick="setView('top')">📐 Plan</button>
  <button onclick="setView('front')">🏠 Façade</button>
  <button onclick="setView('side')">👈 Profil</button>
  <button onclick="toggleWire()">🔲 Filaire</button>
  <button onclick="toggleRotate()">🔄 Auto</button>
</div>

<script type="importmap">
{"imports": {
  "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
  "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
}}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const DATA = ''' + json.dumps(scene_data) + ''';

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a2e);
scene.fog = new THREE.Fog(0x1a1a2e, 20, 60);

const camera = new THREE.PerspectiveCamera(50, innerWidth/innerHeight, 0.5, 100);
camera.position.set(14, 10, 16);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.2;
document.body.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(5.5, 2.5, 4.2);
controls.autoRotate = true;
controls.autoRotateSpeed = 0.4;
controls.maxPolarAngle = Math.PI / 2.1;

// Lighting
const ambient = new THREE.AmbientLight(0x404050, 1.5);
scene.add(ambient);
const sun = new THREE.DirectionalLight(0xffeedd, 5);
sun.position.set(15, 25, 5);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.near = 0.5;
sun.shadow.camera.far = 60;
sun.shadow.camera.left = -25;
sun.shadow.camera.right = 25;
sun.shadow.camera.top = 25;
sun.shadow.camera.bottom = -25;
sun.shadow.bias = -0.0001;
scene.add(sun);
const fill = new THREE.DirectionalLight(0xaabbdd, 2);
fill.position.set(-8, 2, -5);
scene.add(fill);
const rim = new THREE.DirectionalLight(0xffffff, 1);
rim.position.set(0, 0.5, 15);
scene.add(rim);

// Ground
const groundGeo = new THREE.PlaneGeometry(40, 40);
const groundMat = new THREE.MeshStandardMaterial({
  color: 0x3a3a2a, roughness: 0.95, metalness: 0
});
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI/2;
ground.position.y = -0.01;
ground.receiveShadow = true;
scene.add(ground);

// Grid
const grid = new THREE.GridHelper(30, 30, 0x555566, 0x2a2a3e);
grid.position.y = 0.001;
scene.add(grid);

// Build house mesh
const geo = new THREE.BufferGeometry();
geo.setIndex(new THREE.BufferAttribute(new Uint32Array(DATA.faces.flat()), 1));
geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(DATA.vertices.flat()), 3));
geo.computeVertexNormals();

// Vertex colors
const pos = geo.attributes.position.array;
const colors = new Float32Array(pos.length);
for (let i = 0; i < pos.length; i += 3) {
  const z = pos[i+2];
  if (z < 0.31) {
    colors[i]=0.55; colors[i+1]=0.48; colors[i+2]=0.42; // fondation
  } else if (z > 2.7 && z < 2.72) {
    colors[i]=0.68; colors[i+1]=0.58; colors[i+2]=0.50; // plafond
  } else if (z > 4.7) {
    colors[i]=0.67; colors[i+1]=0.23; colors[i+2]=0.18; // toit
  } else if (z < 0.32) {
    colors[i]=0.62; colors[i+1]=0.55; colors[i+2]=0.48;
  } else {
    colors[i]=0.82; colors[i+1]=0.74; colors[i+2]=0.68; // murs
  }
}
geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

const mat = new THREE.MeshStandardMaterial({
  vertexColors: true, roughness: 0.75, metalness: 0.02
});
const house = new THREE.Mesh(geo, mat);
house.castShadow = true;
house.receiveShadow = true;
scene.add(house);

// Wireframe
const wire = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
  color: 0x889999, wireframe: true, transparent: true, opacity: 0.12
}));
wire.visible = false;
scene.add(wire);

document.getElementById('loading').style.display = 'none';

// Controls
window.setView = (v) => {
  document.querySelectorAll('#controls button').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  const t = new THREE.Vector3(5.5, 2.5, 4.2);
  controls.target.copy(t);
  if (v==='top') camera.position.set(t.x, t.y+14, t.z+0.1);
  else if (v==='front') camera.position.set(t.x, t.y+2, t.z-14);
  else if (v==='side') camera.position.set(t.x+14, t.y+2, t.z);
  else camera.position.set(14, 10, 16);
  controls.update();
};
window.toggleWire = () => { wire.visible = !wire.visible; event.target.classList.toggle('active'); };
window.toggleRotate = () => { controls.autoRotate = !controls.autoRotate; event.target.classList.toggle('active'); };

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
animate();
window.addEventListener('resize', () => {
  camera.aspect = innerWidth/innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
</script>
</body>
</html>'''

    path = str(OUT_DIR / "viewer_3d.html")
    Path(path).write_text(html)
    print(f"✅ Viewer Web → {path}")
    return path


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🏠  ARCHIPLAN 3D — Rendu Architectural Professionnel")
    print("=" * 60)
    
    print("\n📄 Plan 2D architectural...")
    plan_path = create_architectural_plan()
    
    print("\n🧊 Construction 3D...")
    mesh, obj_path, metadata = build_architectural_3d()
    
    print("\n📸 Rendu vues architecturales...")
    preview_path = render_architectural_views(mesh, metadata)
    
    print("\n🌐 Viewer Web interactif...")
    viewer_path = generate_web_viewer(mesh, metadata)
    
    print("\n" + "=" * 60)
    print("✅ MAISON ARCHITECTURALE TERMINÉE")
    print(f"   Plan       : {plan_path}")
    print(f"   Modèle 3D  : {obj_path}")
    print(f"   Rendu      : {preview_path}")
    print(f"   Viewer Web : {viewer_path}")
    print(f"   Surface    : {HOUSE_W*HOUSE_D:.1f} m²")
    print(f"   Pièces     : {len(ROOMS)}")
    print("=" * 60)
