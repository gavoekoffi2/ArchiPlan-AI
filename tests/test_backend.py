"""Tests unitaires du backend ArchiPlan AI."""
from fastapi.testclient import TestClient

import main as backend


client = TestClient(backend.app)


# ─── Tests d'endpoints ──────────────────────────────────────────────

def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "models" in body


def test_demo_model_structure():
    r = client.get("/api/demo-model")
    assert r.status_code == 200
    model = r.json()["model"]
    assert "metadata" in model
    assert isinstance(model["rooms"], list) and len(model["rooms"]) > 0
    assert isinstance(model["walls"], list) and len(model["walls"]) > 0
    assert isinstance(model["doors"], list)
    assert isinstance(model["windows"], list)
    assert model["floor"]["width"] > 0


def test_build_3d_rejects_empty():
    r = client.post("/api/build-3d", json={})
    assert r.status_code == 400
    r = client.post("/api/build-3d", json={"analysis": {}})
    assert r.status_code == 400


def test_build_3d_minimal():
    analysis = {
        "rooms": [
            {"name": "Salon", "x": 0, "z": 0, "width": 4, "depth": 5},
        ],
        "walls": [],
        "doors": [],
        "windows": [],
        "total_width": 8,
        "total_depth": 6,
    }
    r = client.post("/api/build-3d", json={"analysis": analysis, "file_id": "test_unit"})
    assert r.status_code == 200
    model = r.json()["model"]
    assert len(model["rooms"]) == 1
    assert model["rooms"][0]["name"] == "Salon"
    # Murs périmètre auto-générés
    assert len(model["walls"]) >= 4


def test_estimate_cost():
    demo = client.get("/api/demo-model").json()["model"]
    r = client.post("/api/estimate-cost", json={"model": demo, "price_per_m2": 2000})
    assert r.status_code == 200
    body = r.json()
    assert body["surface_habitable_m2"] > 0
    assert body["price_per_m2"] == 2000
    assert body["total_cost_eur"] == round(body["surface_habitable_m2"] * 2000, 2)


def test_estimate_cost_default_price():
    demo = client.get("/api/demo-model").json()["model"]
    r = client.post("/api/estimate-cost", json={"model": demo})
    assert r.status_code == 200
    assert r.json()["price_per_m2"] > 0


def test_export_obj_404():
    r = client.get("/api/export-obj/inexistant_xyz")
    assert r.status_code == 404


def test_export_obj_ok():
    # Construire un modèle d'abord
    analysis = {
        "rooms": [{"name": "Test", "x": 0, "z": 0, "width": 3, "depth": 3}],
        "walls": [], "doors": [], "windows": [],
        "total_width": 4, "total_depth": 4,
    }
    client.post("/api/build-3d", json={"analysis": analysis, "file_id": "test_obj"})
    r = client.get("/api/export-obj/test_obj")
    assert r.status_code == 200
    text = r.text
    assert "# ArchiPlan AI" in text
    assert text.count("\nv ") > 8  # au moins quelques sommets


# ─── Tests fonctions internes ────────────────────────────────────────

def test_validate_analysis_ok():
    valid = {
        "rooms": [{"name": "A", "width": 3, "depth": 4}],
        "total_width": 5, "total_depth": 6,
    }
    assert backend.validate_analysis(valid) is True


def test_validate_analysis_rejected():
    assert backend.validate_analysis({}) is False
    assert backend.validate_analysis({"rooms": []}) is False
    assert backend.validate_analysis({"rooms": [{"width": 0, "depth": 4}], "total_width": 5, "total_depth": 5}) is False
    assert backend.validate_analysis({"rooms": [{"width": 3, "depth": 4}], "total_width": -1, "total_depth": 5}) is False
    # Pièce démesurée
    assert backend.validate_analysis({"rooms": [{"width": 100, "depth": 4}], "total_width": 5, "total_depth": 5}) is False


def test_extract_json_with_markdown():
    text = '```json\n{"a": 1, "b": [1,2]}\n```'
    assert backend.extract_json(text) == {"a": 1, "b": [1, 2]}


def test_extract_json_with_noise():
    text = 'Voici la sortie : {"x": 42} merci !'
    assert backend.extract_json(text) == {"x": 42}


def test_extract_json_invalid():
    assert backend.extract_json("aucun json") == {}
    assert backend.extract_json("") == {}


def test_generate_perimeter_walls():
    rooms = [
        {"x": 0, "z": 0, "width": 4, "depth": 5},
        {"x": 4, "z": 0, "width": 3, "depth": 5},
    ]
    walls = backend.generate_perimeter_walls(rooms, 7, 5, 2.7, 0.15)
    # 4 murs périmètre + au moins 1 mur partagé entre les 2 pièces
    assert len(walls) >= 5


def test_model_to_obj_contains_geometry():
    model = backend.generate_3d_model(backend.generate_standard_house())
    obj = backend.model_to_obj(model)
    # Doit contenir des vertex (v) et des faces (f)
    assert "\nv " in obj
    assert "\nf " in obj
    assert "o sol" in obj
    assert obj.count("\no mur_") >= 4


# ─── Rate limit ─────────────────────────────────────────────────────

def test_rate_limit_logic():
    # Reset
    backend._rate_log.clear()
    ip = "127.0.0.99"
    # Doit autoriser jusqu'à RATE_LIMIT_PER_HOUR
    allowed = [backend.check_rate_limit(ip) for _ in range(backend.RATE_LIMIT_PER_HOUR)]
    assert all(allowed)
    # La suivante doit refuser
    assert backend.check_rate_limit(ip) is False
