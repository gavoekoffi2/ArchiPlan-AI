# 🏗️ ArchiPlan AI — Architecture 3D Intelligente

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-teal)](https://fastapi.tiangolo.com)
[![Three.js](https://img.shields.io/badge/Three.js-r150-black)](https://threejs.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

> **Transforme n'importe quel plan 2D en modèle 3D visitable en 30 secondes — avec IA.**

Télécharge une image de plan (PNG/JPG) → L'IA analyse → Modèle 3D généré automatiquement avec meubles → Visite virtuelle dans le navigateur.

**Zero installation. Zero configuration. 100% web.**

---

## ✨ Fonctionnalités

| Fonctionnalité | Description |
|----------------|-------------|
| 🧠 **Analyse IA du plan** | Gemini Vision / GPT-4o / Claude analysent le plan et détectent automatiquement les pièces, murs, portes, fenêtres |
| 🏠 **Génération 3D automatique** | Murs, sols, pièces colorées, portes, fenêtres — tout est généré en JSON structuré |
| 🪑 **Meubles automatiques** | Placement intelligent selon le type de pièce (canapé/salon, lit/chambre, baignoire/SDB, cuisine...) |
| 🖱️ **Vue orbite 3D** | Rotation, zoom, pan — clic sur une pièce pour zoomer |
| 🚶 **Visite virtuelle FPS** | WASD + souris pour marcher dans la maison comme dans un jeu vidéo |
| 🎨 **Code couleur par pièce** | Chaque pièce a sa couleur distincte pour une lisibilité immédiate |
| 🔧 **Ajout/suppression de meubles** | Menu 8 types de meubles, ajout en 1 clic |
| 🧱 **Toggle murs** | Afficher/masquer les murs pour voir l'aménagement |
| 📐 **Stats en temps réel** | Surface totale, nombre de murs/portes/fenêtres |

---

## 🚀 Démo live

```
http://76.13.129.252:9090
```

Clique sur **✨ Démo** pour voir une maison 5 pièces avec meubles.

---

## 📋 Stack technique

### Backend (Python/FastAPI)

| Outil | Version | Rôle |
|-------|---------|------|
| **FastAPI** | 0.115+ | API REST pour upload, analyse, génération 3D |
| **Uvicorn** | 0.34+ | Serveur ASGI |
| **httpx** | 0.28+ | Client HTTP async pour appels API externes |
| **OpenCV** | 4.x | Fallback computer vision si l'IA échoue |
| **OpenRouter** | — | Gateway unifiée vers Gemini, GPT-4o, Claude (vision) |

### Frontend (Vanilla JS + Three.js)

| Outil | Version | Rôle |
|-------|---------|------|
| **Three.js** | r150.1 | Rendu 3D WebGL temps réel |
| **OrbitControls** | — | Navigation orbite (rotation/zoom/pan) |
| **PointerLockControls** | — | Visite virtuelle FPS (WASD + souris) |

### Modèles IA utilisés

| Modèle | Priorité | Usage |
|--------|----------|-------|
| `google/gemini-2.0-flash-001` | ⭐ 1er | Analyse vision du plan (meilleur pour plans architecturaux) |
| `openai/gpt-4o` | ⭐ 2ème | Fallback si Gemini échoue |
| `anthropic/claude-sonnet-4` | ⭐ 3ème | Dernier recours IA |
| OpenCV (analyse contours) | 🔄 Fallback | Analyse basique si tous les modèles IA échouent |

---

## 🔧 Installation locale

### Prérequis
- Python 3.10+ **ou** Docker
- Clé API OpenRouter (pour l'analyse IA)

### Option A — Docker (recommandé)

```bash
git clone https://github.com/gavoekoffi2/ArchiPlan-AI.git
cd ArchiPlan-AI
cp .env.example .env       # puis renseignez OPENROUTER_API_KEY
docker compose up -d
```

L'app est dispo sur `http://localhost:9090`.

### Option B — Python natif

```bash
git clone https://github.com/gavoekoffi2/ArchiPlan-AI.git
cd ArchiPlan-AI
pip install -r requirements.txt
export OPENROUTER_API_KEY="sk-or-v1-..."
python app/main.py
```

### Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## 🏛️ Architecture

```
ArchiPlan-AI/
├── app/
│   ├── main.py              # Backend FastAPI (routes, IA, génération 3D)
│   ├── static/
│   │   └── index.html       # Frontend Three.js complet (33 Ko de pur JS)
│   ├── uploads/             # Plans uploadés
│   └── output/              # Modèles 3D générés (JSON)
├── build_pro_house.py       # Ancien prototype (générateur géométrique)
├── pipeline.py              # Ancien pipeline prototype
├── pdf_parser.py            # Ancien parser PDF
└── README.md
```

### Flux de données

```
1. Upload image (PNG/JPG)
      ↓
2. POST /api/analyze-plan
      ↓
3. Encodage base64 → appel OpenRouter (Gemini Vision)
      ↓
4. IA retourne JSON structuré : {rooms, walls, doors, windows, dimensions}
      ↓
5. POST /api/build-3d → génération modèle 3D complet
      ↓
6. Frontend Three.js : rendu des murs, pièces, portes, fenêtres, meubles
      ↓
7. Interaction utilisateur : orbite, visite, meubles, stats
```

### Format du modèle 3D (JSON)

```json
{
  "metadata": {"total_width": 10, "total_depth": 8, "wall_height": 2.7, "units": "meters"},
  "rooms": [
    {"name": "Salon", "x": 0, "z": 0, "width": 5, "depth": 5, "color": "#f4a460"}
  ],
  "walls": [
    {"x": 5.0, "z": 0.075, "length": 10, "height": 2.7, "thickness": 0.15, "rotation": 0}
  ],
  "doors": [
    {"x": 4.5, "z": 0, "y": 1.05, "width": 0.9, "height": 2.1, "rotation": 0, "color": "#8B7355"}
  ],
  "windows": [
    {"x": 1.5, "z": 0, "y": 1.2, "width": 1.2, "height": 1.2, "rotation": 0}
  ],
  "camera": {"position": {"x": 5, "y": 8, "z": 10}, "lookAt": {"x": 5, "y": 0, "z": 4}},
  "floor": {"width": 10, "depth": 8, "y": 0, "color": "#c8b898"}
}
```

---

## 🧠 Comment améliorer le projet

### Améliorations IA

1. **Fine-tuner un modèle de segmentation** sur le dataset [CubiCasa5K](https://github.com/CubiCasa/CubiCasa5k) pour une détection plus précise des murs/portes/fenêtres
2. **Ajouter DALL-E/FLUX via OpenRouter** pour générer des textures photo-réalistes par pièce
3. **Détection automatique des cotes** (chiffres sur le plan) pour un dimensionnement exact
4. **Support des PDF vectoriels** (pas juste images raster)

### Améliorations 3D

1. **Remplacer les meubles cubiques par des modèles glTF** (bibliothèque 3D réaliste)
2. **Ajouter des textures** sur les murs/sols (parquet, carrelage, peinture)
3. **Mode VR** avec WebXR API
4. **Ombres et éclairage dynamique** (heure du jour, lampes)
5. **Toit/plafond** généré automatiquement

### Améliorations UI/UX

1. **Sauvegarder/charger des projets** (localStorage ou backend)
2. **Export OBJ/glTF/IFC** pour logiciels BIM
3. **Partage de projet** par lien
4. **Mode comparaison** (avant/après ameublement)
5. **Responsive mobile** (vue simplifiée)

### Améliorations techniques

1. **Rate limiting** sur l'upload (éviter les abus)
2. **Cache Redis** pour les modèles générés
3. **Docker** pour déploiement simplifié
4. **CI/CD GitHub Actions** pour déploiement automatique
5. **Tests unitaires** (pytest)

---

## 🐛 Bugs connus

| Bug | Priorité | Commentaire |
|-----|----------|-------------|
| Modèles IA parfois lents (10-20s) | Moyenne | Timeout augmentable dans `call_openrouter()` |
| Meubles déposés au centre si pas de pièce détectée | Basse | Ajouter placement contextuel |
| Visite FPS peut traverser les murs | Moyenne | Ajouter collision detection (raycasting) |
| Couleurs de pièces pastel peu contrastées | Basse | Palette configurable dans `room_colors` |

---

## 📝 Notes pour développeurs

### Travailler avec Claude Code

```bash
# Cloner et lancer Claude Code
git clone https://github.com/gavoekoffi2/ArchiPlan-AI.git
cd ArchiPlan-AI
claude
```

### Points d'entrée clés

- **`app/main.py`** : Tout le backend — routes API, analyse IA, génération 3D
  - `ai_analyze_floor_plan()` — appel à l'IA (ligne ~143)
  - `generate_3d_model()` — conversion analyse → modèle 3D (ligne ~240)
  - `basic_cv_analysis()` — fallback OpenCV (ligne ~230)
- **`app/static/index.html`** : Tout le frontend Three.js (~900 lignes)
  - `buildScene()` — rendu complet de la scène 3D
  - `autoPlaceFurniture()` — placement automatique des meubles
  - `setMode('walk')` — mode visite FPS

### Conventions de code

- **Backend** : Python 3.11+, typage optionnel, docstrings en français
- **Frontend** : Vanilla JS (ES modules), Three.js r150, CSS custom properties
- **Coordonnées** : Système XZ (Y=hauteur), mètres, origine = coin supérieur gauche
- **Couleurs** : Hexadécimal, palette pastel distincte pour les pièces

---

## 🔑 Variables d'environnement

| Variable | Requise | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | Oui | Clé API OpenRouter (modèles vision) |

Le fichier `.env` dans `~/.hermes/.env` est chargé automatiquement.

---

## 📄 Licence

MIT — Free for commercial use, modification, distribution.

---

**Créé par [GAVOE Koffi Claude](https://github.com/gavoekoffi2)** · Propulsé par l'IA
