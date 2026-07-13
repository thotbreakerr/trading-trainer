from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.spa import SPAStaticFiles


def test_spa_static_files_falls_back_only_for_client_routes(tmp_path):
    (tmp_path / "index.html").write_text("<main>trainer</main>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=tmp_path, html=True), name="frontend")
    client = TestClient(app)

    assert client.get("/learn/module/7").text == "<main>trainer</main>"
    assert client.get("/journal/42").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/missing").status_code == 404
