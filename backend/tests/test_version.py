"""
GET /api/version (Section 8 Settings footer, Batch 9, Section 11 item 19).
Must read the baked file, never compute a value at runtime — a running
container's version can't legitimately change without a rebuild.
"""
import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_version_falls_back_to_dev_when_no_baked_file(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.version.VERSION_FILE", str(tmp_path / "does-not-exist.json"))
    response = client.get("/api/version")
    assert response.status_code == 200
    body = response.json()
    assert body["git_sha"] == "dev"
    assert body["build_date"] is None


def test_version_reads_the_baked_file(monkeypatch, tmp_path):
    version_file = tmp_path / "version.json"
    version_file.write_text(json.dumps({"git_sha": "abc1234", "build_date": "2026-07-16T18:00:00Z"}))
    monkeypatch.setattr("app.api.version.VERSION_FILE", str(version_file))
    response = client.get("/api/version")
    assert response.status_code == 200
    assert response.json() == {"git_sha": "abc1234", "build_date": "2026-07-16T18:00:00Z"}


def test_version_falls_back_on_malformed_baked_file(monkeypatch, tmp_path):
    version_file = tmp_path / "version.json"
    version_file.write_text("not valid json{{{")
    monkeypatch.setattr("app.api.version.VERSION_FILE", str(version_file))
    response = client.get("/api/version")
    assert response.status_code == 200
    assert response.json()["git_sha"] == "dev"
