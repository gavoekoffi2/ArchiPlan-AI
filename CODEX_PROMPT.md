# 🎯 PROMPT POUR CODEX — ArchiPlan AI : finaliser pour la production

Tu es un développeur senior avec 20+ ans d'expérience en applications web 3D, Three.js, FastAPI, IA générative et architecture. Tu reprends le projet **ArchiPlan AI** (https://github.com/gavoekoffi2/ArchiPlan-AI) là où l'équipe précédente s'est arrêtée. Ton objectif : **finir ce produit pour qu'il soit utilisable par de vrais architectes en production**.

---

## 📦 CONTEXTE — Ce qu'est ArchiPlan AI

Application web qui transforme **un plan d'architecture 2D (PNG/JPG)** en **modèle 3D meublé et visitable** via une intelligence artificielle (Gemini Vision / GPT-4o / Claude). L'utilisateur upload son plan → l'IA analyse → un modèle 3D est généré avec murs, portes, fenêtres, meubles ; l'utilisateur peut faire le tour en orbite, en visite FPS, en tour cinématographique avec enregistrement vidéo.

**Cible** : architectes, agents immobiliers, particuliers en construction.
**Démo** : http://76.13.129.252:9090
**Repo** : gavoekoffi2/ArchiPlan-AI · branche de travail = `master` (push direct → déploiement webhook automatique)

---

## 🏛️ ARCHITECTURE TECHNIQUE

```
ArchiPlan-AI/
├── app/
│   ├── main.py              ← Backend FastAPI 0.115 (970 lignes)
│   │   Endpoints : /api/health, /api/analyze-plan, /api/build-3d,
│   │   /api/model/{id}, /api/demo-model, /api/estimate-cost,
│   │   /api/export-obj/{id}, /api/modify-plan (commande IA),
│   │   /api/deploy (webhook GitHub)
│   ├── static/
│   │   └── index.html       ← Frontend ESM Three.js r150 (2860 lignes,
│   │                          tout dans 1 seul fichier : HTML+CSS+JS)
│   ├── uploads/             ← Plans uploadés
│   ├── output/              ← Modèles 3D JSON (+ cache .cache/<hash>.json)
│   └── logs/                ← archiplan.log (rotation 2 Mo × 3)
├── tests/test_backend.py    ← 16 tests pytest (tous verts)
├── Dockerfile               ← Python 3.11-slim + OpenCV headless
├── docker-compose.yml
├── deploy.sh                ← Webhook : pull + pip + pytest + restart
├── requirements.txt         ← Versions pinnées
└── README.md
```

**Stack** : FastAPI + Uvicorn + httpx (async) · OpenRouter Gateway (Gemini 2.0 Flash → GPT-4o → Claude Sonnet 4 → fallback OpenCV) · Three.js r150.1 (OrbitControls, PointerLockControls, OBJExporter, STLExporter, GLTFExporter, RoundedBoxGeometry, RoomEnvironment, PMREMGenerator) · MediaRecorder API pour enregistrement vidéo · CanvasTexture pour parquet/mur procéduraux.

**Format JSON du modèle 3D** :
```json
{
  "metadata": {"total_width": 10, "total_depth": 8, "wall_height": 2.7, "units": "meters", "source": "..."},
  "rooms": [{"name", "type", "x", "z", "width", "depth", "color"}],
  "walls": [{"x", "z", "length", "height", "thickness", "rotation"}],
  "doors": [{"x", "z", "y", "width", "height", "rotation", "color"}],
  "windows": [{"x", "z", "y", "width", "height", "rotation"}],
  "floor": {"width", "depth", "y", "color"},
  "camera": {"position", "lookAt"}
}
```
**Système de coordonnées** : XZ horizontal (Y=hauteur), mètres, origine = coin haut-gauche du plan.
**Convention rotation meubles** : à `rotation=0`, le **dos du meuble pointe vers -Z** (canapé, lit, etc.).
**Rotations contre les murs** : N=0, S=π, W=π/2, E=-π/2 (mur N = z faible).

---

## ✅ FONCTIONNALITÉS DÉJÀ IMPLÉMENTÉES (à conserver et améliorer)

### Backend (`app/main.py`)
- **Pipeline IA cascade** : Gemini Vision → GPT-4o → Claude Sonnet → fallback OpenCV (`basic_cv_analysis`). Prompt très structuré dans `PROMPT_ANALYSE` (détecte cotes, échelle, orientation, types de pièces).
- **Cache d'analyse** SHA-256 de l'image → zéro re-analyse pour le même plan.
- **Validation stricte** de la sortie IA (`validate_analysis`) : refus du fallback silencieux vers une maison standard. Erreur 502 explicite si tout échoue.
- **Rate limit** in-memory 60 req/h par IP (`check_rate_limit`).
- **Limite upload** 8 Mo + validation Content-Type.
- **Logging fichier rotatif** + console détaillée.
- **No-cache headers** (`/`, `*.html`) pour éviter cache navigateur après déploiement.
- **Endpoint `/api/modify-plan`** : commande IA en langage naturel ("ajoute une chambre 4×3 m avec lit et armoire") qui modifie le plan via OpenRouter.
- **Endpoint `/api/estimate-cost`** : surface habitable + plancher + coût (€/m² configurable).
- **Endpoint `/api/export-obj`** côté serveur (Wavefront OBJ).
- **Endpoint `/api/deploy`** : webhook GitHub qui lance `deploy.sh`.

### Frontend (`app/static/index.html`)
- **Three.js r150** : scène + OrbitControls + PointerLockControls (FPS).
- **RoomEnvironment + PMREMGenerator** : env map indispensable pour que les matériaux à `metalness` (verre, miroir, métal, frigo, voiture) ne rendent pas en noir.
- **Cadrage adaptatif** (`computeModelBBox` + `fitLightsAndCameraToBBox`) : caméra, soleil, shadow camera frustum ajustés à la **bounding box réelle** des pièces (et non à `total_width` qui peut être faux). `maxDistance` = 5× la diagonale.
- **Pas de fog**, `camera.near=0.1`, `camera.far=500`.
- **Auto-récupération** : si plus aucun mur détecté dans la scène → `buildScene()` automatique.
- **Try/catch global** dans `animate()` : un crash ne tue plus la boucle.
- **WebGL context loss/restore** listeners : récupération auto si le GPU perd le contexte.
- **PointLights des plafonniers LIMITÉES à 4 max** (au-delà : mesh visuel seulement, sans PointLight).
- **Validation dimensions murs** avant création BoxGeometry (anti-NaN).
- **Textures procédurales** (CanvasTexture) : parquet et mur.

**Modes de vue** :
- 🖱️ **Orbite** (par défaut)
- 🚶 **Visite FPS** : pointer lock + drag-look fallback, collision via raycaster dédié (NE PAS partager avec le raycaster de hover), curseur masqué en lock, overlay "Commencer la visite" avec instructions (carte WASD/Souris/Shift/Esc).
- 🎬 **Tour cinématographique automatique** : FOV temporaire à 72°, toit extérieur auto-masqué, pour chaque pièce 8 plans (entrée diagonale + transition + 6 angles 360° depuis le centre + sortie). Durée ~16s/pièce. Easing cubique. Demande "Enregistrer en vidéo ?" : si oui → MediaRecorder API → modal avec lecteur intégré + bouton **⬇️ Télécharger (.webm)**. Détection codec automatique (vp9 → vp8 → defaults).

**UI** :
- **Toolbar gauche** (icônes draggable) : 📋 sidebar · 🪑 meubles · 🧱 murs · ☀️🌙 jour/nuit · 🏠 toit · 🎬 tour · 📦📐🖨️📸📊 exports OBJ/glTF/STL/PNG/JSON · 💶 coût · ✏️ édition pièces · 🔄 reset
- **Bottombar** discrète (Orbite/Visite) en bas-droite, semi-transparente, ne masque plus la 3D.
- **Dropdown "Aller à une pièce"** centré en bas (n'occulte plus la 3D).
- **Barre commande IA naturelle** au-dessus du dropdown : *"ajoute une chambre 4×3"* + Entrée.
- **Sidebar droite** (cachée par défaut, draggable) : surfaces, structure, liste pièces.
- **Panneau Meubles** (draggable) : 33 boutons d'ajout manuel.
- **Toutes les panneaux** : draggables par poignée `⋮⋮`, positions persistées en `localStorage`.
- **Thème clair/sombre** persisté en `localStorage`.
- **Loading skeleton** animé avec messages contextuels.

**Toit** :
- Plafond intérieur + toiture extérieure à 2 pans avec faîtage + débord.
- **Auto-cull** : quand la caméra est ≤ 85% de la hauteur du faîtage, le toit extérieur disparaît automatiquement pour qu'on voie l'intérieur. Plafond intérieur reste toujours visible.
- Restauration auto à la fin du tour cinématographique.

**Mobilier — 33 types modélisés en `createFurnitureMesh(type)`** :
Coins arrondis via `RoundedBoxGeometry` partout où ça compte. Helpers : `mk()` (box), `rmk()` (rounded), `mkCyl()`, `mkSphere()`.

Liste complète :
- Salon : `sofa` (3 places, 4 coussins déco rotation aléatoire, plaid), `table` (basse, pile livres, tasse, vase+fleurs), `tv` (avec meuble TV), `bookshelf` (livres aléatoires + objets déco + plante + cadre photo), `armchair`, `floor_lamp`, `fireplace` (avec feu animé), `rug` (6 palettes aléatoires).
- Chambre : `bed` (6 PALETTES aléatoires couleur literie, tête de lit capitonnée avec boutons), `single_bed`, `crib` (berceau bébé avec barreaux), `nightstand`, `wardrobe`, `dresser` (commode), `vanity` (coiffeuse avec miroir rond + flacons + tabouret), `toy_chest`, `lamp`, `mirror`, `painting` (7 couleurs aléatoires).
- Cuisine : `kitchen` (bloc complet : armoires + plan + plaque 4 brûleurs + hotte + armoires hautes), `fridge` (2 portes), `oven` (porte vitrée + boutons), `microwave`, `dishwasher`, `sink` (vasque + robinet + miroir).
- SDB : `bathtub`, `shower` (parois vitrées 90×90), `toilet`, `towel_rack` (2 serviettes pendues).
- Bureau : `desk` (avec ordinateur portable + caisson tiroirs), `chair`, `filing_cabinet`, `printer`.
- Salle à manger : `dining_table` (mise en place 4-6 couverts).
- Entrée : `console` (avec vase + clés), `coat_rack` (avec manteau), `shoe_rack` (3 niveaux + paires colorées).
- Garage : `car` (sedan complète : chassis + cabine + 4 vitres + 4 roues + phares), `workbench` (étau + outils + panneau mural), `toolbox`, `storage_box` (cartons).
- Salle de réunion : `conference_table` (3×1.2 m + 12 verres + carafe + documents), `whiteboard` (marqueurs colorés).
- Divers : `plant` (3 sphères de feuillage), `curtain` (2 panneaux + tringle + plis, placement auto devant chaque fenêtre), `ceiling_lamp` (suspension avec PointLight), `shelf` (étagère murale + déco).

**Placement automatique par pièce** (`autoPlaceFurniture`) :
- Détection robuste par `room.type` ET regex sur `room.name` (français + anglais).
- 5 sous-types de chambres : `master` (lit + 2 chevets + coiffeuse + fauteuil), `child` (lit simple + bureau + coffre), `baby` (berceau + commode), `guest` (lit + chevet unique), `standard`.
- Classement automatique : plus grande chambre = master, plus petite = child.
- Chaque pièce a sa logique propre (salon/cuisine/sdb/wc/bureau/dining/entrée/garage/rangement/salle de réunion).
- Filet de sécurité : si rien n'a été placé → au moins une plante au centre.
- Helper `placeAgainstWall(room, wall, type, t, clearance)` ancre les meubles aux murs avec rotation correcte.

**Exports** :
- 📦 OBJ (client-side via OBJExporter ; server-side via `/api/export-obj`)
- 📐 glTF (GLTFExporter)
- 🖨️ STL ASCII (STLExporter) — pour Revit, AutoCAD, ArchiCAD, Fusion 360, FreeCAD, Blender, Cura
- 📸 PNG screenshot (toDataURL après render)
- 📊 Rapport JSON (surfaces, structure, meubles, pièces détaillées)

**Tests** : `tests/test_backend.py` = 16 tests pytest (endpoints, validation, OBJ export, rate limit). Tous verts. CI : `python -m pytest tests/ -q`.

**Déploiement** :
- `Dockerfile` Python 3.11-slim + OpenCV headless + curl.
- `docker-compose up -d` → `http://localhost:9090`.
- `deploy.sh` webhook : pull + pip + pytest + redémarrage uvicorn.
- Variables : `OPENROUTER_API_KEY`, `ARCHIPLAN_RATE_LIMIT=60`, `ARCHIPLAN_PRICE_M2=1800`.

---

## ⚠️ BUGS CONNUS QUI PERSISTENT (à investiguer en priorité)

### 🐛 BUG #1 — La 3D "disparaît" quand l'utilisateur manipule la caméra
**Symptôme** : pendant un drag/orbite/zoom, des pans entiers du modèle deviennent invisibles ou noirs.

**Pistes déjà testées et résolues** : fog supprimé, polygonOffset retiré, sols colorés des pièces retirés (BoxGeometry transparent), sprites text retirés (depthTest:false toxique), shadow camera bbox-adaptive, PMREM RoomEnvironment ajouté, PointLights limitées à 4, no-cache headers, WebGL context loss handler, validation dimensions murs.

**Pistes à explorer si le bug persiste encore** :
1. **Frustum culling sur BufferGeometry du toit** : le `geom.computeVertexNormals()` du toit en 2 pans utilise un BufferGeometry custom. Vérifier que la bounding sphere est correcte (`geom.computeBoundingSphere()`).
2. **Camera near = 0.1** : si l'utilisateur zoome très près d'un objet, le near plane peut clipper. Tester `near=0.05` ou utiliser logarithmicDepthBuffer.
3. **Antialiasing FXAA/MSAA** sur certains GPU AMD avec PMREMGenerator : tenter `WebGLRenderer({ antialias: false })` + EffectComposer FXAA.
4. **OrbitControls.target.y=1.0** peut traverser le sol si l'utilisateur dézoome très bas. Verrouiller `controls.minPolarAngle = 0.1` (pas 0).
5. **Materials clonés** : `wallMat.clone()` × N murs → fuite de matériaux non disposés. Audit : utiliser UN seul `wallMat` partagé pour tous les murs.
6. **Test manuel avec `renderer.info.render`** dans la console pour voir si draw calls chutent à 0.

### 🐛 BUG #2 — Plans complexes mal analysés
L'IA Gemini renvoie parfois des `total_width` incorrects ou des pièces qui se chevauchent. Le frontend reste robuste grâce à `computeModelBBox`, mais la qualité du rendu se dégrade.

### 🐛 BUG #3 — Fenêtres et portes mal orientées
Convention de rotation incohérente entre le format de données (rotation=0 sur mur N) et le mesh (BoxGeometry avec axe X = épaisseur). **Vérifier** : si `wall.rotation=0` = mur courant en X, alors la fenêtre/porte sur ce mur doit avoir `rotation=π/2` pour aligner son axe long (Z) sur le mur. Aujourd'hui c'est inversé selon les cas.

### 🐛 BUG #4 — Curtains placement
Le placement automatique des rideaux devant chaque fenêtre ne sait pas distinguer "intérieur de la pièce" vs "extérieur". Solution : calculer la pièce qui contient le centre de la fenêtre, puis placer le rideau de ce côté.

---

## 🚀 FEATURES À AJOUTER POUR LA PRODUCTION

### Priorité P0 — Bloquantes pour premiers utilisateurs

1. **Authentification utilisateur** (login email/Google/GitHub OAuth) + persistance des projets en DB (SQLite local d'abord). Schéma : `users(id, email, created_at)`, `projects(id, user_id, name, analysis_json, model_json, created_at)`.
2. **Liste "Mes projets"** : affichage des projets sauvegardés, ouvrir/dupliquer/supprimer.
3. **Sauvegarde manuelle** + bouton 💾 dans la toolbar.
4. **Annuler/Refaire** (Ctrl+Z / Ctrl+Y) sur les modifications de pièces et placements.
5. **Validation des plans complexes** : tester avec 5-10 plans réels (maisons d'architecte, plans cadastraux, croquis manuscrits) et identifier les failure modes.
6. **Diagnostic du bug #1** définitivement résolu avec preuve (vidéo + console logs).
7. **Mobile responsive** : aujourd'hui l'UI ne fonctionne pas bien sur tablette/téléphone (tour FPS impossible, panneaux trop grands).

### Priorité P1 — Très souhaitables

8. **Édition manuelle des murs** en mode 2D : retour vue plan, drag-and-drop pour déplacer/redimensionner les murs, ajouter/supprimer des portes/fenêtres au clic.
9. **Catalogue de meubles étendu** : modèles glTF externes (Sketchfab CC0, Three.js examples) pour meubles photoréalistes au lieu de procéduraux. Avec lazy loading.
10. **IFC export** (Industry Foundation Classes) : standard BIM. Bibliothèque : `web-ifc` côté client ou `ifcopenshell` côté serveur.
11. **Mode VR** via WebXR API (Three.js a déjà un VRButton).
12. **Génération de textures par IA** : DALL-E 3 ou FLUX via OpenRouter pour parquet/papier peint photo-réalistes.
13. **PDF parser** : accepter aussi les PDF vectoriels d'architecte (utiliser `pdf2image` + même pipeline).
14. **Bibliothèque de plans types** : "maison 4 chambres", "appartement T3", "loft", "studio" en démos.
15. **Sharing par lien** : `/p/<short_id>` pour partager un projet public en lecture seule.

### Priorité P2 — Différenciants

16. **Multi-étages** : R+1, R-1, sous-sol. Refactor du format pour avoir `floors: [{level, rooms, walls, ...}]`.
17. **Calcul énergétique** : estimation chauffage/isolation selon surface et orientation.
18. **Détection automatique meubles existants** dans le plan source (lits dessinés, etc.) via vision IA.
19. **Modèles de scènes** : "loft new-yorkais", "maison provençale", "appartement scandinave" → packs de matériaux + meubles cohérents.
20. **Collaboration temps réel** : 2 utilisateurs sur le même projet (WebSocket).
21. **API publique** : permettre aux outils tiers d'exploiter l'analyse IA via REST.

### Priorité P3 — Polish

22. **Onboarding interactif** au premier login (3 étapes : upload → analyse → visite).
23. **Tutoriel vidéo** intégré accessible depuis la toolbar.
24. **i18n** : EN + ES + DE (actuellement FR uniquement).
25. **Accessibilité WCAG AA** : navigation clavier complète, ARIA labels, contraste.
26. **Mode lecture seule** pour clients d'architectes (URL avec token).

---

## 🛡️ RÈGLES DE TRAVAIL (à respecter strictement)

- **Branche `master` directe** : push direct = déploiement webhook automatique (~10s). Pas de PR.
- **Avant tout commit** : `python -m pytest tests/ -q` doit passer (sinon le deploy.sh n'avance pas).
- **Avant tout commit** : `node --check` sur le bloc `<script type="module">` extrait de `index.html` pour valider la syntaxe JS (sinon écran blanc en prod).
- **Code en français** pour commentaires/docstrings/messages utilisateur.
- **Three.js r150** uniquement (pas d'upgrade r160+ qui casse beaucoup d'addons).
- **OpenRouter** comme seul provider IA (la clé est dans `~/.hermes/.env` côté serveur).
- **Pas de dépendance Python lourde** (déjà 6 deps + tests).
- **Tout dans `index.html`** (CSS + JS inline) : pas de bundler, pas de build step. Volontaire pour simplifier déploiement.
- **Préserver les conventions** : système XZ (Y=hauteur), mètres, origine coin haut-gauche, dos meuble en -Z à rotation 0.
- **Logs serveur** : utiliser le logger `archiplan` configuré, pas `print()`.
- **Erreurs utilisateur** : messages clairs en français, jamais de stack trace nue.

---

## 🎯 CRITÈRES DE "PRODUCTION READY"

L'app est prête pour les premiers utilisateurs réels quand :
1. ✅ Tous les tests pytest passent (`pytest -q` : 16/16 verts).
2. ✅ Le bug #1 (disparition) est résolu et testé sur Chrome + Firefox + Safari + tablette.
3. ✅ Auth + sauvegarde de projets fonctionne (P0).
4. ✅ 5 plans réels différents génèrent un modèle 3D correct sans erreur.
5. ✅ Lighthouse score > 80 sur Performance et Accessibilité.
6. ✅ L'app fonctionne en mode incognito (pas de dépendance localStorage critique).
7. ✅ Erreurs gracieuses : aucun crash blanc, toujours un message utilisateur.
8. ✅ README à jour avec captures d'écran et démo vidéo.
9. ✅ `docker compose up -d` démarre l'app et passe le healthcheck en < 30s.
10. ✅ Rate limiting validé (61e requête refusée proprement).

---

## 📍 PAR OÙ COMMENCER

1. Clone : `git clone https://github.com/gavoekoffi2/ArchiPlan-AI.git && cd ArchiPlan-AI`
2. Lis `app/main.py` (970 l) et `app/static/index.html` (2860 l) en intégralité.
3. Lance localement : `pip install -r requirements.txt && cd app && python main.py` (port 9090).
4. Ouvre la démo : http://localhost:9090 → clique "✨ Démo" → manipule la caméra → essaie d'identifier le bug #1.
5. **Première session** : viser à résoudre définitivement le bug #1 + ajouter l'authentification basique (SQLite + cookies session). Commit `Fix bug disparition + auth basique` → push master → vérifier déploiement.
6. Ensuite, dérouler la liste P0 dans l'ordre.

**Ne pas chercher à tout refondre.** Le code est tactique mais fonctionnel. Préserve l'esprit "un seul fichier index.html" : c'est ce qui permet à un architecte non-tech de cloner et déployer en 30 secondes.

Bonne chance — il ne reste plus grand-chose entre cet état actuel et un produit que tu pourras livrer fièrement.
