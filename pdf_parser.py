#!/usr/bin/env python3
"""
ARCHIPLAN 3D — Parsing PDF/DWG de plans d'architecte
Extrait les plans 2D depuis des fichiers PDF, DWG, DXF
"""
import fitz  # PyMuPDF
import ezdxf
import numpy as np
from pathlib import Path
from PIL import Image
import io

OUT_DIR = Path("/tmp/archiplan3d_output")


def parse_pdf_floor_plan(pdf_path: str) -> list[tuple[str, Image.Image]]:
    """
    Extrait toutes les pages/images d'un PDF de plan d'architecte.
    Retourne une liste de (nom_page, image_PIL).
    """
    doc = fitz.open(pdf_path)
    pages = []
    
    for i, page in enumerate(doc):
        # Rendu haute résolution
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        
        # Détecter si c'est un plan (beaucoup de lignes noires sur fond blanc)
        arr = np.array(img.convert("L"))
        dark_pixels = np.sum(arr < 128)
        total = arr.size
        darkness_ratio = dark_pixels / total
        
        # Un plan a typiquement 5-20% de pixels sombres
        if 0.03 < darkness_ratio < 0.40:
            name = f"page_{i+1}"
            pages.append((name, img))
            print(f"   ✅ Page {i+1} : plan détecté ({darkness_ratio:.1%} lignes)")
        else:
            print(f"   ⏭️  Page {i+1} : ignorée ({darkness_ratio:.1%} — pas un plan)")
    
    doc.close()
    return pages


def parse_dxf_floor_plan(dxf_path: str) -> dict:
    """
    Extrait les murs et lignes d'un fichier DXF (AutoCAD).
    Retourne les données structurées des murs.
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    lines = []
    
    # Extraire toutes les lignes
    for entity in msp.query("LINE"):
        lines.append({
            "x1": entity.dxf.start.x,
            "y1": entity.dxf.start.y,
            "x2": entity.dxf.end.x,
            "y2": entity.dxf.end.y,
        })
    
    # Extraire les polylignes
    for entity in msp.query("LWPOLYLINE"):
        pts = list(entity.get_points())
        for i in range(len(pts) - 1):
            lines.append({
                "x1": pts[i][0], "y1": pts[i][1],
                "x2": pts[i+1][0], "y2": pts[i+1][1],
            })
    
    print(f"   ✅ DXF : {len(lines)} lignes extraites")
    
    # Calculer les bounding box
    if lines:
        all_x = [l["x1"] for l in lines] + [l["x2"] for l in lines]
        all_y = [l["y1"] for l in lines] + [l["y2"] for l in lines]
        
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        
        # Normaliser
        for l in lines:
            l["x1"] = l["x1"] - min_x
            l["y1"] = l["y1"] - min_y
            l["x2"] = l["x2"] - min_x
            l["y2"] = l["y2"] - min_y
        
        W = max_x - min_x
        H = max_y - min_y
    
    # Classifier les lignes (murs extérieurs vs intérieurs)
    exterior = []
    interior = []
    
    for l in lines:
        length = np.sqrt((l["x2"]-l["x1"])**2 + (l["y2"]-l["y1"])**2)
        if length < 1.0:  # Ignorer les très courtes lignes
            continue
        
        # Vérifier si la ligne est proche du bord
        x1, y1 = l["x1"], l["y1"]
        x2, y2 = l["x2"], l["y2"]
        
        near_edge = (
            min(x1, x2) < W * 0.05 or max(x1, x2) > W * 0.95 or
            min(y1, y2) < H * 0.05 or max(y1, y2) > H * 0.95
        )
        
        line_data = {
            "x1": float(x1), "y1": float(y1),
            "x2": float(x2), "y2": float(y2),
            "label": f"ligne_{len(exterior)+len(interior)}",
        }
        
        if near_edge:
            exterior.append(line_data)
        else:
            interior.append(line_data)
    
    # Détecter les pièces (rectangles formés par les murs)
    rooms = []
    # Version simplifiée : grille basée sur les coordonnées uniques
    unique_x = sorted(set([l["x1"] for l in lines] + [l["x2"] for l in lines]))
    unique_y = sorted(set([l["y1"] for l in lines] + [l["y2"] for l in lines]))
    
    room_names = ["Salon", "Cuisine", "Chambre 1", "Chambre 2", "SDB", "Couloir", "Bureau", "Garage"]
    
    for i in range(len(unique_x) - 1):
        for j in range(len(unique_y) - 1):
            x1, x2 = unique_x[i], unique_x[i+1]
            y1, y2 = unique_y[j], unique_y[j+1]
            w, h = x2 - x1, y2 - y1
            if w > 1.0 and h > 1.0:
                rooms.append({
                    "name": room_names[len(rooms)] if len(rooms) < len(room_names) else f"Pièce_{len(rooms)+1}",
                    "x": float(x1), "y": float(y1),
                    "w": float(w), "h": float(h),
                })
    
    return {
        "exterior": exterior,
        "interior": interior,
        "rooms": rooms,
        "image_size": [float(W), float(H)],
        "wall_height": 2.7,
        "wall_thickness": 0.2,
        "source": "DXF",
    }


def parse_any_plan(file_path: str) -> dict:
    """
    Détecte le type de fichier et parse automatiquement.
    Supporte : PDF, DXF, DWG (via DXF), PNG, JPG.
    """
    ext = Path(file_path).suffix.lower()
    
    if ext == '.pdf':
        print(f"\n📄 Parsing PDF : {file_path}")
        pages = parse_pdf_floor_plan(file_path)
        if pages:
            # Sauvegarder la première page
            name, img = pages[0]
            img_path = str(OUT_DIR / f"plan_from_{Path(file_path).stem}.png")
            img.save(img_path)
            print(f"   💾 Plan extrait → {img_path}")
            return {"type": "pdf", "pages": len(pages), "image_path": img_path}
        return {"type": "pdf", "pages": 0, "error": "Aucun plan détecté"}
    
    elif ext in ['.dxf', '.dwg']:
        print(f"\n📐 Parsing {ext.upper()} : {file_path}")
        walls = parse_dxf_floor_plan(file_path)
        return {"type": "dxf", "walls": walls}
    
    elif ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff']:
        print(f"\n🖼️  Image plan : {file_path}")
        return {"type": "image", "image_path": file_path}
    
    else:
        return {"type": "unknown", "error": f"Format non supporté : {ext}"}


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 pdf_parser.py <fichier.pdf|.dxf|.png>")
        sys.exit(1)
    
    result = parse_any_plan(sys.argv[1])
    import json
    print(f"\n📊 Résultat : {json.dumps({k: v for k, v in result.items() if k != 'walls'}, indent=2, ensure_ascii=False)}")
