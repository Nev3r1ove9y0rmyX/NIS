"""证据文件下载用例（决策 D-02）。

覆盖：本人可下载、他人 404、文件不存在 404、路径穿越被拒、下载写审计。
"""

from __future__ import annotations

import hashlib
import importlib

import pytest
from fastapi.testclient import TestClient

from conftest import ensure_schema, import_service
from test_auth import ADMIN_PASSWORD, DEMO_PASSWORD, AsgiBridge

API = "/api/v1"


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def write(self, **kwargs) -> bool:  # noqa: ANN003
        self.events.append(kwargs)
        return True


@pytest.fixture
def stack(tmp_path, monkeypatch):
    from nis_shared.clients import IamClient, InternalClient
    from nis_shared.db import Database

    monkeypatch.setenv("EVIDENCE_ROOT", str(tmp_path))

    import_service("iam-service")
    iam_db = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(iam_db)
    seed = importlib.import_module("app.seed")
    seed.seed(iam_db, admin_password=ADMIN_PASSWORD, demo_password=DEMO_PASSWORD)
    iam_app = importlib.import_module("app.main").app
    iam_app.state.database = iam_db
    iam_app.state.audit = RecordingAudit()
    iam_bridge = AsgiBridge(iam_app)

    import_service("recon-service")
    recon_app = importlib.import_module("app.main").app
    recon_db = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(recon_db)
    recon_app.state.database = recon_db
    recon_audit = RecordingAudit()
    recon_app.state.audit = recon_audit
    recon_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    recon_bridge = AsgiBridge(recon_app)

    import_service("api-gateway")
    gateway_app = importlib.import_module("app.main").app
    gateway_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    gateway_app.state.iam_http = InternalClient("http://iam-service:8001", transport=iam_bridge)
    gateway_app.state.recon_http = InternalClient("http://recon-service:8002", transport=recon_bridge)
    gateway_app.state.audit = RecordingAudit()

    return {
        "client": TestClient(gateway_app),
        "root": tmp_path,
        "recon_audit": recon_audit,
    }


def login(client: TestClient, username: str, password: str = DEMO_PASSWORD) -> str:
    response = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _record_with_evidence(client: TestClient, token: str, file_name: str, payload: bytes) -> dict:
    sha = hashlib.sha256(payload).hexdigest()
    response = client.post(
        f"{API}/recon-records",
        headers=headers(token),
        json={
            "title": "证据下载验证",
            "source_type": "osint",
            "content": "用于验证证据文件受控下载的记录，内容足够长以通过校验。",
            "credibility": "medium",
            "priority": "normal",
            "evidence": [
                {"file_name": file_name, "media_type": "image/png", "size_bytes": len(payload), "sha256": sha}
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _place_file(root, record_id: str, file_name: str, payload: bytes):  # noqa: ANN001
    directory = root / "recon" / record_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / file_name
    path.write_bytes(payload)
    return path


def test_owner_can_download_evidence(stack) -> None:
    client = stack["client"]
    token = login(client, "recon01")
    payload = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    record = _record_with_evidence(client, token, "现场照片.png", payload)

    evidence_id = record["evidence"][0]["id"]
    _place_file(stack["root"], record["id"], "现场照片.png", payload)

    response = client.get(
        f"{API}/recon-records/{record['id']}/evidence/{evidence_id}", headers=headers(token)
    )
    assert response.status_code == 200, response.text
    assert response.content == payload
    assert response.headers["content-type"].startswith("image/png")

    audit = stack["recon_audit"]
    downloads = [event for event in audit.events if event["action"] == "evidence.download"]
    assert downloads and downloads[-1]["result"] == "success"
    assert downloads[-1]["details"]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_other_user_cannot_download_evidence(stack) -> None:
    client = stack["client"]
    owner = login(client, "recon01")
    payload = b"secret-photo"
    record = _record_with_evidence(client, owner, "secret.png", payload)
    evidence_id = record["evidence"][0]["id"]
    _place_file(stack["root"], record["id"], "secret.png", payload)

    other = login(client, "recon02")
    response = client.get(
        f"{API}/recon-records/{record['id']}/evidence/{evidence_id}", headers=headers(other)
    )
    assert response.status_code == 404

    denied = [e for e in stack["recon_audit"].events if e["action"] == "evidence.download"]
    assert denied and denied[-1]["result"] == "denied"


def test_missing_file_is_404(stack) -> None:
    client = stack["client"]
    token = login(client, "recon01")
    record = _record_with_evidence(client, token, "not-there.png", b"x")
    evidence_id = record["evidence"][0]["id"]

    response = client.get(
        f"{API}/recon-records/{record['id']}/evidence/{evidence_id}", headers=headers(token)
    )
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


def test_unknown_evidence_id_is_404(stack) -> None:
    client = stack["client"]
    token = login(client, "recon01")
    record = _record_with_evidence(client, token, "a.png", b"x")

    response = client.get(
        f"{API}/recon-records/{record['id']}/evidence/00000000-0000-4000-8000-000000000000",
        headers=headers(token),
    )
    assert response.status_code == 404


def test_storage_path_rejects_traversal(tmp_path, monkeypatch) -> None:
    from nis_shared.errors import ApiError
    from nis_shared.storage import resolve_storage_path

    monkeypatch.setenv("EVIDENCE_ROOT", str(tmp_path))
    (tmp_path / "ok.txt").write_text("ok", encoding="utf-8")

    assert resolve_storage_path("ok.txt").name == "ok.txt"
    for bad in ("../etc/passwd", "/etc/passwd", "recon/../../x", ""):
        with pytest.raises(ApiError):
            resolve_storage_path(bad)
