from __future__ import annotations

from fastapi.testclient import TestClient

from moos_map.web import app


client = TestClient(app)


def test_health_and_static_app_load() -> None:
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.get("/")
    assert response.status_code == 200
    assert "MOOS Map" in response.text


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
            "source_id": "usgs-imagery",
        },
    )

    assert response.status_code == 200
    plan = response.json()
    assert plan["tiles"]["count"] == 4
    assert plan["pixel_width"] == 512
    assert "estimated_max_vertical_mapping_error_m" in plan


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
