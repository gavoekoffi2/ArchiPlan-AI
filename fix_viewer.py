#!/usr/bin/env python3
"""
ARCHIPLAN 3D — Viewer fixé
- Orientation corrigée (Y = hauteur Three.js)
- Z-fighting résolu
- Ombres portées propres
"""
import json, math
from pathlib import Path

OUT_DIR = Path("/tmp/archiplan3d_output")

# Charger les vertices du modèle
import trimesh
mesh = trimesh.load(str(OUT_DIR / "maison_3d.obj"))

# Convertir les vertices : Z (hauteur architecture) → Y (hauteur Three.js)
# Coordonnées originales : X=largeur, Y=profondeur, Z=hauteur
# Three.js a besoin de : X=largeur, Y=hauteur, Z=profondeur (ou X, Z)
verts = mesh.vertices.copy()
# Rotation : (x, y, z) → (x, z, y)  — met Z en Y
verts_three = verts[:, [0, 2, 1]].tolist()
faces = mesh.faces.tolist()

scene_data = json.dumps({"vertices": verts_three, "faces": faces})

html = f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>ArchiPlan 3D — Maison Résidentielle</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#1a1a2e; font-family:'Segoe UI',system-ui,sans-serif; overflow:hidden; }}
canvas {{ display:block; }}
#info {{
  position:fixed; top:16px; left:16px; z-index:10;
  background:rgba(15,15,25,0.9); color:#d4c8b8; padding:14px 20px;
  border-radius:12px; font-size:13px; border:1px solid rgba(255,255,255,0.06);
  pointer-events:none;
}}
#info h1 {{ font-size:19px; color:#f0e4d4; margin-bottom:4px; }}
#info .specs {{ color:#988878; font-size:11px; }}
#controls {{
  position:fixed; bottom:20px; left:50%; transform:translateX(-50%); z-index:10;
  background:rgba(15,15,25,0.92); padding:10px 16px; border-radius:28px;
  display:flex; gap:6px; flex-wrap:wrap; justify-content:center;
  border:1px solid rgba(255,255,255,0.05);
}}
#controls button {{
  background:transparent; color:#b0a090; border:1px solid rgba(255,255,255,0.08);
  padding:8px 14px; border-radius:18px; cursor:pointer; font-size:12px;
  transition:all 0.2s; white-space:nowrap; font-family:inherit;
}}
#controls button:hover {{ background:rgba(255,255,255,0.06); color:#e0d0c0; }}
#controls button.active {{ background:#8b4513; color:#fff; border-color:#a0522d; }}
</style>
</head>
<body>
<div id="info">
  <h1>🏠 Maison Résidentielle</h1>
  <div class="specs">11.0×8.5m · 93.5m² · 7 pièces</div>
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
{{"imports":{{
  "three":"https://unpkg.com/three@0.160.0/build/three.module.js",
  "three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"
}}}}
</script>
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

const DATA = {scene_data};

// ─── SCENE ────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf0ebe0);
scene.fog = new THREE.Fog(0xf0ebe0, 25, 80);

// ─── CAMERA ───────────────────────────────────
const camera = new THREE.PerspectiveCamera(50, innerWidth/innerHeight, 0.5, 120);
camera.position.set(15, 10, 15);
camera.lookAt(5.5, 1.5, 4.2);

// ─── RENDERER ─────────────────────────────────
const renderer = new THREE.WebGLRenderer({{ antialias:true, alpha:false }});
renderer.setSize(innerWidth, innerHeight);
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.1;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

// ─── ORBIT CONTROLS ───────────────────────────
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(5.5, 1.5, 4.2);
controls.autoRotate = true;
controls.autoRotateSpeed = 0.4;
controls.maxPolarAngle = Math.PI * 0.48;
controls.minDistance = 4;
controls.maxDistance = 40;
controls.update();

// ─── LIGHTS ───────────────────────────────────
const ambient = new THREE.AmbientLight(0x606878, 2.0);
scene.add(ambient);

const sun = new THREE.DirectionalLight(0xffeedd, 6);
sun.position.set(18, 22, 2);
sun.castShadow = true;
sun.shadow.mapSize.width = 2048;
sun.shadow.mapSize.height = 2048;
sun.shadow.camera.near = 0.5;
sun.shadow.camera.far = 80;
sun.shadow.camera.left = -25;
sun.shadow.camera.right = 25;
sun.shadow.camera.top = 25;
sun.shadow.camera.bottom = -25;
sun.shadow.bias = -0.0003;
sun.shadow.normalBias = 0.02;
scene.add(sun);

const fill = new THREE.DirectionalLight(0xaabbdd, 2.5);
fill.position.set(-10, 3, -8);
scene.add(fill);

const rim = new THREE.HemisphereLight(0xddeeff, 0x889966, 1.0);
scene.add(rim);

// ─── GROUND ───────────────────────────────────
const groundGeo = new THREE.PlaneGeometry(50, 50);
const groundMat = new THREE.MeshStandardMaterial({{
  color:0x335522, roughness:0.9, metalness:0
}});
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI/2;
ground.position.y = -0.02;
ground.receiveShadow = true;
scene.add(ground);

// ─── GRID ────────────────────────────────────
const grid = new THREE.GridHelper(24, 24, 0x888888, 0xcccccc);
grid.position.y = 0.005;
grid.material.transparent = true;
grid.material.opacity = 0.25;
scene.add(grid);

// ─── BUILD HOUSE ──────────────────────────────
const geo = new THREE.BufferGeometry();
const allFaces = DATA.faces.flat();
const allVerts = DATA.vertices.flat();

geo.setIndex(new THREE.BufferAttribute(new Uint32Array(allFaces), 1));
geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(allVerts), 3));
geo.computeVertexNormals();

// Vertex colors by component
const pos = geo.attributes.position.array;
const colors = new Float32Array(pos.length);

for (let i = 0; i < pos.length; i += 3) {{
  const y = pos[i+1]; // Y = hauteur dans Three.js
  const x = pos[i+0];
  const z = pos[i+2];
  
  if (y < 0.32) {{
    // Fondations / sol
    colors[i]=0.55; colors[i+1]=0.48; colors[i+2]=0.42;
  }} else if (y > 4.7) {{
    // Toit tuile
    colors[i]=0.67; colors[i+1]=0.22; colors[i+2]=0.17;
  }} else if (y > 2.7 && y < 2.75) {{
    // Plafond
    colors[i]=0.64; colors[i+1]=0.55; colors[i+2]=0.48;
  }} else {{
    // Murs crépi beige
    colors[i]=0.82; colors[i+1]=0.74; colors[i+2]=0.66;
  }}
}}
geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

const mat = new THREE.MeshStandardMaterial({{
  vertexColors:true, roughness:0.7, metalness:0.03,
  polygonOffset:true, polygonOffsetFactor:1, polygonOffsetUnit:1
}});

const house = new THREE.Mesh(geo, mat);
house.castShadow = true;
house.receiveShadow = true;
scene.add(house);

// ─── WIREFRAME ────────────────────────────────
const wireMat = new THREE.MeshBasicMaterial({{
  color:0x667788, wireframe:true, transparent:true, opacity:0.08,
  depthTest:true, depthWrite:false
}});
const wire = new THREE.Mesh(geo, wireMat);
wire.visible = false;
wire.renderOrder = 1;
scene.add(wire);

// ─── VIEW CONTROLS ────────────────────────────
window.setView = (v) => {{
  document.querySelectorAll('#controls button').forEach(b=>b.classList.remove('active'));
  event.target.classList.add('active');
  const t = new THREE.Vector3(5.5, 1.5, 4.2);
  controls.target.copy(t);
  if (v==='top') camera.position.set(t.x, t.y+16, t.z+0.01);
  else if (v==='front') camera.position.set(t.x, t.y+1.5, t.z-16);
  else if (v==='side') camera.position.set(t.x+16, t.y+1.5, t.z);
  else camera.position.set(15, 10, 15);
  controls.update();
}};
window.toggleWire = () => {{ wire.visible=!wire.visible; event.target.classList.toggle('active'); }};
window.toggleRotate = () => {{ controls.autoRotate=!controls.autoRotate; event.target.classList.toggle('active'); }};

// ─── ANIMATE ──────────────────────────────────
function animate() {{
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}}
animate();

window.addEventListener('resize', () => {{
  camera.aspect = innerWidth/innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}});
</script>
</body>
</html>'''

viewer_path = OUT_DIR / "viewer_3d.html"
viewer_path.write_text(html)
print(f"✅ Viewer fixé → {viewer_path}")
print(f"   • Orientation corrigée (Y = hauteur)")
print(f"   • Z-fighting résolu (polygonOffset)")
print(f"   • Fond clair, ombres propres")
print(f"   • {len(allFaces)//3} faces, {len(allVerts)//3} sommets")
