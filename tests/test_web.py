from __future__ import annotations

from fastapi.testclient import TestClient

from moos_map.web import app


client = TestClient(app)


def test_health_and_static_app_load() -> None:
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "MOOS Map Builder" in response.text
    assert 'id="zoom" type="range" min="0" max="22" value="17"' in response.text
    assert "Advanced placement" in response.text
    assert '<span class="section-kicker">04</span>' in response.text
    assert 'id="overlay"' not in response.text
    assert '<details id="source-details" class="compact-details">' in response.text
    assert "Highest-detail satellite option from Anaxi" not in response.text
    assert 'id="overwrite"' not in response.text
    assert 'id="refresh-tiles"' in response.text
    assert 'id="emit-moos" type="checkbox" checked' in response.text
    assert "Include .moos mission snippet" in response.text
    assert 'id="force"' not in response.text
    assert "Build Map" in response.text
    assert "Build exact crop" not in response.text
    assert "draggable: true" in client.get("/static/app.js").text
    assert 'addEventListener("input", applyCornerInputs)' in client.get("/static/app.js").text
    assert client.get("/static/app.js").headers["cache-control"] == "no-store, max-age=0"
    assert "placement-drawer" not in response.text


def test_sources_api_lists_only_the_curated_source_set() -> None:
    payload = client.get("/api/sources").json()

    assert set(payload) == {"sources"}
    assert {source["id"] for source in payload["sources"]} == {
        "google-maps",
        "google-satellite",
        "google-hybrid",
        "esri-world-imagery",
        "esri-world-topo",
    }


def test_plan_api_defaults_to_zoom_17() -> None:
    response = client.post(
        "/api/plan",
        json={
            "bounds": {
                "west": -71.088,
                "south": 42.358,
                "east": -71.087,
                "north": 42.359,
            },
            "origin": {"latitude": 42.3585, "longitude": -71.0875},
            "source_id": "google-satellite",
        },
    )

    assert response.status_code == 200
    assert response.json()["tiles"]["zoom"] == 17


def test_plan_api_uses_shared_core() -> None:
    response = client.post(
        "/api/plan",
        json={
            "bounds": {
                "west": -71.088,
                "south": 42.358,
                "east": -71.087,
                "north": 42.359,
            },
            "origin": {"latitude": 42.3585, "longitude": -71.0875},
            "zoom": 16,
            "source_id": "google-satellite",
        },
    )

    assert response.status_code == 200
    plan = response.json()
    assert plan["tiles"]["count"] == 4
    assert plan["pixel_width"] < 512
    assert plan["pixel_height"] < 512
    assert plan["actual_bounds"] == plan["requested_bounds"]
    assert plan["download_bounds"] != plan["requested_bounds"]
    assert plan["estimated_tiff_size_bytes"] == plan["pixel_count"] * 3
    assert "estimated_max_vertical_mapping_error_m" in plan

    app_js = client.get("/static/app.js").text
    assert 'metric("Viewer size"' not in app_js
    assert "Estimated TIFF size" in app_js
    assert "Exact on-disk size" in app_js
    assert "model max" in app_js


def test_blank_output_directory_is_accepted_by_plan_and_rejected_by_build() -> None:
    payload = {
        "bounds": {
            "west": -71.088,
            "south": 42.358,
            "east": -71.087,
            "north": 42.359,
        },
        "origin": {"latitude": 42.3585, "longitude": -71.0875},
        "zoom": 17,
        "source_id": "google-satellite",
        "output_dir": "",
    }

    assert client.post("/api/plan", json=payload).status_code == 200
    response = client.post("/api/build", json=payload)
    assert response.status_code == 400
    assert "Choose an output directory" in response.json()["error"]


def test_api_returns_user_facing_domain_error() -> None:
    response = client.post(
        "/api/plan",
        json={
            "bounds": {"west": -72.1, "south": 42, "east": -71.9, "north": 42.1},
            "origin": {"latitude": 42.05, "longitude": -72},
            "zoom": 16,
        },
    )

    assert response.status_code == 400
    assert "UTM zone" in response.json()["error"]
