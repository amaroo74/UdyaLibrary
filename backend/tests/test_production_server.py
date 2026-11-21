from fastapi.testclient import TestClient

from app.main import FRONTEND_DIST_DIR, app


client = TestClient(app)


def test_health_route_is_available():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_docs_and_openapi_are_not_captured_by_spa_fallback():
    assert client.get("/docs").status_code == 200
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "Udaya Library Dataset API"


def test_spa_index_is_served_when_frontend_build_exists():
    if not (FRONTEND_DIST_DIR / "index.html").is_file():
        raise AssertionError(f"Frontend build missing at {FRONTEND_DIST_DIR}; run npm run build first")

    response = client.get("/catalogue")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root"></div>' in response.text


def test_unknown_api_path_is_not_rewritten_to_index():
    response = client.get("/api/not-a-real-route")

    assert response.status_code == 404
