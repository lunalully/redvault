"""Platform-level integration tests.

These tests boot the real FastAPI application (lifespan, content seeding,
SQLite, lab manager) against an isolated temporary data directory. They never
touch the operator's real REDVAULT database, session cookie or lab processes.

Run with:  python3 -m pytest tests/test_platform.py -v
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import tempfile

import httpx
import pytest

# IMPORTANT: configuration reads REDVAULT_DATA at import time. Set it before
# importing any app module so the database, secret key and lab state are all
# isolated from the real installation.
_TEST_DATA = tempfile.mkdtemp(prefix="redvault-platform-test-")
os.environ["REDVAULT_DATA"] = _TEST_DATA
os.environ.setdefault("REDVAULT_BOT", "0")
os.environ.setdefault("REDVAULT_LAB_START_TIMEOUT", "20")
atexit.register(lambda: shutil.rmtree(_TEST_DATA, ignore_errors=True))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.flags import derive_flag  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AuthSession,
    Challenge,
    Flag,
    LabSession,
    ObjectiveState,
    Progress,
    User,
)

from app.config import LOCAL_OPERATOR  # noqa: E402

USERNAME = LOCAL_OPERATOR


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _csrf_from_page(client: TestClient) -> str:
    response = client.get("/settings")
    assert response.status_code == 200, response.text
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.text)
    assert match, "CSRF meta tag missing from authenticated page"
    return match.group(1)


def ensure_logged_in(client: TestClient) -> str:
    """REDVAULT has no login: the first page view issues the local session."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200, response.text
    assert "rv_session" in client.cookies
    return _csrf_from_page(client)


@pytest.fixture(scope="session")
def session(client):
    csrf = ensure_logged_in(client)
    yield {"client": client, "csrf": csrf}
    # Stop anything left running; the app lifespan also does this.
    for row in client.get("/api/labs").json().get("labs", []):
        client.post(
            f"/api/challenges/{row['slug']}/stop",
            headers={"X-CSRF-Token": csrf},
        )


def api_headers(csrf: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# First run, authentication and CSRF
# ---------------------------------------------------------------------------

def test_local_operator_has_no_login(client):
    # The dashboard is served immediately: no setup screen, no sign-in form.
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "Operações" in response.text
    assert 'name="password"' not in response.text

    # A browser without the session cookie still gets the operator dashboard,
    # and the response issues the per-browser CSRF session.
    fresh = TestClient(app)
    first = fresh.get("/", follow_redirects=False)
    assert first.status_code == 200
    assert "rv_session" in first.cookies
    assert "Operações" in first.text

    with SessionLocal() as db:
        assert db.query(User).count() == 1
        user = db.query(User).one()
        assert user.username == "operator"
        assert not user.password_hash
        auth = db.query(AuthSession).filter_by(user_id=user.id).first()
        assert auth.csrf_token
        assert auth.token_hash != first.cookies["rv_session"]

    # Old authentication URLs now land on the dashboard.
    for path in ("/login", "/setup"):
        assert client.get(path, follow_redirects=False).status_code == 303
        assert client.get(path, follow_redirects=False).headers["location"] == "/"


def test_inline_scripts_and_handlers_respect_csp(client):
    """No template may ship an inline script or inline handler the CSP blocks.

    The CSP allows inline scripts only through the hash of the pre-paint snippet
    in base.html and never allows ``'unsafe-inline'``. Any other inline
    ``<script>``, ``onclick=`` or ``onload=`` is silently dead in the browser:
    that is how the learning-path "Nova trilha"/"Notas" toggles and the
    certificate "Imprimir" button broke. Behaviour belongs in /static/js/app.js.
    """
    import base64
    import hashlib
    from pathlib import Path

    templates_dir = Path(__file__).resolve().parents[1] / "app" / "templates"
    csp = client.get("/").headers["content-security-policy"]
    script_src = next(part.strip() for part in csp.split(";") if part.strip().startswith("script-src"))
    assert "'unsafe-inline'" not in script_src

    problems: list[str] = []
    for template_path in sorted(templates_dir.glob("*.html")):
        html = template_path.read_text()
        for match in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S):
            digest = base64.b64encode(hashlib.sha256(match.group(1).encode()).digest()).decode()
            if f"'sha256-{digest}'" not in script_src:
                problems.append(f"{template_path.name}: inline <script> without a CSP hash")
        for match in re.finditer(r"\son[a-z]+\s*=\s*\"[^\"]*\"", html):
            problems.append(f"{template_path.name}: inline handler {match.group(0).strip()}")
    assert not problems, "blocked by CSP: " + "; ".join(problems)

    # The pre-paint script must stay: it applies the sidebar state before paint.
    template = (templates_dir / "base.html").read_text()
    inline = re.search(r"<script>(.*?)</script>", template, re.S)
    assert inline, "base.html must keep the pre-paint script"
    digest = base64.b64encode(hashlib.sha256(inline.group(1).encode()).digest()).decode()
    assert f"'sha256-{digest}'" in script_src, "CSP hash no longer matches the pre-paint script"


def test_csrf_still_required_for_mutating_requests(session):
    client = session["client"]
    assert client.post("/settings/session").status_code == 403

    rotated = client.post("/settings/session", data={"_csrf": session["csrf"]}, follow_redirects=False)
    assert rotated.status_code == 303
    assert rotated.headers["location"] == "/settings"
    session["csrf"] = _csrf_from_page(client)


def test_html_and_catalog_never_leak_flag_values(session):
    client = session["client"]
    slug = "recon-backup-vault"
    expected = derive_flag(slug, "flag")

    with SessionLocal() as db:
        all_flags = [
            (flag.challenge.slug, flag.key)
            for flag in db.query(Flag).all()
        ]
    derived = {derive_flag(challenge_slug, key) for challenge_slug, key in all_flags}

    for path in ("/", "/challenges", f"/challenges/{slug}", "/machines", "/paths"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        for value in derived:
            assert value not in response.text, f"derived flag leaked in {path}"

    detail = client.get(f"/challenges/{slug}").text
    assert expected not in detail
    assert "Desbloquear hint 1" in detail
    assert "backups/ops.env" not in detail, "hint 3 body must stay locked"
    assert "Desbloquear walkthrough" in detail

    machine = client.get("/machines/machine-nexus-commerce")
    assert machine.status_code == 200
    for value in derived:
        assert value not in machine.text


def test_csrf_required_for_lab_mutation(session):
    client = session["client"]
    response = client.post("/api/challenges/recon-backup-vault/start")
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Lab lifecycle and hint/solution workflow
# ---------------------------------------------------------------------------

def test_lab_start_status_reset_stop(session):
    client = session["client"]
    csrf = session["csrf"]
    slug = "recon-backup-vault"

    started = client.post(f"/api/challenges/{slug}/start", headers=api_headers(csrf))
    assert started.status_code == 200, started.text
    payload = started.json()
    assert payload["active"] is True
    assert payload["status"] == "running"
    port = payload["port"]
    assert 42000 <= port <= 42999

    health = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5)
    assert health.status_code == 200
    assert health.json()["ok"] is True

    status = client.get(f"/api/challenges/{slug}/status")
    assert status.status_code == 200
    assert status.json()["url"] == f"http://127.0.0.1:{port}/"

    reset = client.post(f"/api/challenges/{slug}/reset", headers=api_headers(csrf))
    assert reset.status_code == 200, reset.text
    assert reset.json()["reset_count"] == 1
    new_port = reset.json()["port"]
    assert httpx.get(f"http://127.0.0.1:{new_port}/health", timeout=5).status_code == 200

    stopped = client.post(f"/api/challenges/{slug}/stop", headers=api_headers(csrf))
    assert stopped.status_code == 200
    assert stopped.json()["active"] is False
    with pytest.raises(httpx.HTTPError):
        httpx.get(f"http://127.0.0.1:{new_port}/health", timeout=1)


def test_hint_progression_and_solution_gate(session):
    client = session["client"]
    csrf = session["csrf"]
    slug = "recon-js-bundle"

    blocked = client.post(f"/api/challenges/{slug}/solution", headers=api_headers(csrf))
    assert blocked.status_code == 400
    assert "Desbloqueie todos os 3 hints" in blocked.json()["detail"]

    first = client.post(f"/api/challenges/{slug}/hints/1", headers=api_headers(csrf))
    assert first.status_code == 200, first.text
    assert first.json()["newly_unlocked"] is True
    assert first.json()["hints_used"] == 1
    assert first.json()["hint_penalty"] == 10
    assert "static/app.js" in first.json()["body"]

    duplicate = client.post(f"/api/challenges/{slug}/hints/1", headers=api_headers(csrf))
    assert duplicate.status_code == 200
    assert duplicate.json()["newly_unlocked"] is False
    assert duplicate.json()["hints_used"] == 1

    for level in (2, 3):
        response = client.post(f"/api/challenges/{slug}/hints/{level}", headers=api_headers(csrf))
        assert response.status_code == 200, response.text
        assert response.json()["hints_used"] == level

    unlocked = client.post(f"/api/challenges/{slug}/solution", headers=api_headers(csrf))
    assert unlocked.status_code == 200, unlocked.text
    body = unlocked.json()
    assert body["walkthrough"]
    assert body["root_cause"]
    assert body["mitigation"]
    assert "RV{" not in body["walkthrough"]
    assert "RV{" not in body["root_cause"]
    assert "RV{" not in body["mitigation"]

    again = client.post(f"/api/challenges/{slug}/solution", headers=api_headers(csrf))
    assert again.status_code == 200
    assert again.json()["message"] == "Walkthrough já desbloqueado."

    with SessionLocal() as db:
        user = db.query(User).one()
        challenge = db.query(Challenge).filter_by(slug=slug).one()
        progress = db.query(Progress).filter_by(user_id=user.id, challenge_id=challenge.id).one()
        assert progress.hints_used == 3
        assert progress.hint_penalty == 10 + 15 + 20
        assert progress.solution_unlocked is True


def test_flag_validation_completion_xp_and_duplicate(session):
    client = session["client"]
    csrf = session["csrf"]
    slug = "recon-backup-vault"
    expected = derive_flag(slug, "flag")

    wrong = client.post(
        f"/api/challenges/{slug}/flags",
        headers=api_headers(csrf),
        json={"flag_key": "flag", "value": "RV{not-the-real-value}"},
    )
    assert wrong.status_code == 200
    assert wrong.json()["correct"] is False
    assert wrong.json()["completed"] is False

    accepted = client.post(
        f"/api/challenges/{slug}/flags",
        headers=api_headers(csrf),
        json={"flag_key": "flag", "value": f"  {expected}  "},
    )
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()
    assert result["correct"] is True
    assert result["newly_completed"] is True
    assert result["completed"] is True
    assert result["xp_awarded"] > 0
    assert result["xp_total"] >= result["xp_awarded"]
    assert result["remaining"] == []

    duplicate = client.post(
        f"/api/challenges/{slug}/flags",
        headers=api_headers(csrf),
        json={"flag_key": "flag", "value": expected},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    with SessionLocal() as db:
        user = db.query(User).one()
        challenge = db.query(Challenge).filter_by(slug=slug).one()
        progress = db.query(Progress).filter_by(user_id=user.id, challenge_id=challenge.id).one()
        assert progress.status == "completed"
        assert progress.xp_awarded == result["xp_awarded"]
        flag = db.query(Flag).filter_by(challenge_id=challenge.id, key="flag").one()
        assert expected not in repr(flag.__dict__), "flag value must not be persisted in the flags table"

    dashboard = client.get("/").text
    assert "concluído" in dashboard.lower()


def test_objective_gated_flag(session):
    client = session["client"]
    csrf = session["csrf"]
    slug = "ssrf-image-fetcher"
    expected = derive_flag(slug, "flag")

    rejected = client.post(
        f"/api/challenges/{slug}/flags",
        headers=api_headers(csrf),
        json={"flag_key": "flag", "value": expected},
    )
    assert rejected.status_code == 200
    assert rejected.json()["correct"] is False
    assert "estado de exploração exigido" in rejected.json()["message"]
    assert rejected.json()["completed"] is False

    with SessionLocal() as db:
        user = db.query(User).one()
        challenge = db.query(Challenge).filter_by(slug=slug).one()
        state = ObjectiveState(
            user_id=user.id,
            challenge_id=challenge.id,
            flag_key="flag",
            met=True,
            evidence="integration test: simulated lab callback",
        )
        db.add(state)
        db.commit()

    accepted = client.post(
        f"/api/challenges/{slug}/flags",
        headers=api_headers(csrf),
        json={"flag_key": "flag", "value": expected},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["correct"] is True
    assert accepted.json()["newly_completed"] is True


def test_internal_callback_rejects_unknown_token(client):
    response = client.post(
        "/internal/lab-callback",
        json={"token": "not-a-real-lab-token", "flag_key": "flag"},
    )
    assert response.status_code == 403


def test_started_lab_receives_its_own_session_id(session):
    """The lab must receive its own session id, not the placeholder 0.

    Regression: the LabSession row used to be created *after* the process was
    spawned, so every lab started with ``LAB_SESSION_ID=0`` and each
    ``lab.objective()`` call was rejected with 403. Every lab then refused its
    objective-gated flag ("estado de exploração exigido"), which broke 49 of
    the 97 labs through the real UI while the exploit tests still passed.
    """
    client = session["client"]
    csrf = session["csrf"]
    slug = "ssrf-image-fetcher"

    started = client.post(f"/api/challenges/{slug}/start", headers=api_headers(csrf))
    assert started.status_code == 200, started.text
    port = started.json()["port"]
    try:
        with SessionLocal() as db:
            row = (
                db.query(LabSession)
                .filter_by(port=port)
                .order_by(LabSession.id.desc())
                .first()
            )
        assert row.status == "running" and row.id > 0
        env = _process_env(row.pid)
        assert env["LAB_SESSION_ID"] == str(row.id)
        assert env["LAB_SESSION_ID"] != "0"
        assert env["LAB_CALLBACK_TOKEN"]
    finally:
        client.post(f"/api/challenges/{slug}/stop", headers=api_headers(csrf))


def test_lab_callback_records_the_objective(session):
    """End of the same chain: the token the lab holds is accepted by the API."""
    client = session["client"]
    csrf = session["csrf"]
    slug = "ssrf-image-fetcher"
    started = client.post(f"/api/challenges/{slug}/start", headers=api_headers(csrf))
    port = started.json()["port"]
    try:
        with SessionLocal() as db:
            # Ports are reused between sessions; the live row is the latest one.
            row = (
                db.query(LabSession)
                .filter_by(port=port)
                .order_by(LabSession.id.desc())
                .first()
            )
        token = _process_env(row.pid)["LAB_CALLBACK_TOKEN"]
        response = client.post(
            "/internal/lab-callback",
            json={"token": token, "flag_key": "flag", "evidence": "integration test"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["objective"] == "flag"
        with SessionLocal() as db:
            state = (
                db.query(ObjectiveState)
                .filter_by(user_id=row.user_id, challenge_id=row.challenge_id, flag_key="flag")
                .order_by(ObjectiveState.id.desc())
                .first()
            )
            assert state.met is True
    finally:
        client.post(f"/api/challenges/{slug}/stop", headers=api_headers(csrf))


def test_concurrent_start_stop_does_not_crash_the_manager(session):
    """Two lab operations at once must not corrupt the registry.

    Regression: ``active_for`` iterated the live ``self._labs`` dict while the
    UI's status poller and a start/stop mutated it, raising "dictionary changed
    size during iteration" and taking the whole platform down (500 on every
    page). The iteration now runs over a snapshot.
    """
    import threading

    from app.lab_manager import lab_manager

    client = session["client"]
    csrf = session["csrf"]
    slug = "recon-cloud-listing"
    errors: list[BaseException] = []

    def churn() -> None:
        try:
            for _ in range(25):
                lab_manager.active_labs()
                client.get(f"/api/challenges/{slug}/status")
        except BaseException as exc:  # noqa: BLE001 - collected for the assert
            errors.append(exc)

    client.post(f"/api/challenges/{slug}/start", headers=api_headers(csrf))
    threads = [threading.Thread(target=churn) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    client.post(f"/api/challenges/{slug}/stop", headers=api_headers(csrf))
    assert errors == []
    assert client.get("/health").status_code == 200


def _process_env(pid: int) -> dict[str, str]:
    """Read the environment the lab process was started with (Linux only)."""
    environ = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
    return {
        key.decode(): value.decode()
        for key, _, value in (item.partition(b"=") for item in environ if b"=" in item)
    }


# ---------------------------------------------------------------------------
# Navigation, profile and export
# ---------------------------------------------------------------------------

def test_primary_ui_pages_render(session):
    client = session["client"]
    csrf = session["csrf"]
    assert csrf

    for path in (
        "/",
        "/challenges",
        "/challenges?difficulty=beginner&state=unsolved",
        "/machines",
        "/paths",
        "/paths/web-pentest-fundamentals",
        "/academy",
        "/academy/tools",
        "/academy/glossary",
        "/academy/cves",
        "/environments",
        "/settings",
        "/profile",
        "/profile/export",
        "/health",
    ):
        response = client.get(path)
        assert response.status_code == 200, f"{path}: {response.status_code}\n{response.text[:400]}"

    search = client.get("/api/search", params={"q": "backup"})
    assert search.status_code == 200
    assert search.json()["challenges"]

    # Difficulty, kind and the CVE index are presented in Portuguese, never as
    # raw English keys coming from the manifests.
    detail = client.get("/machines/machine-meridian-bank").text
    assert "Difícil" in detail
    assert ">Máquina<" in detail
    assert ">HARD<" not in detail and ">MACHINE<" not in detail
    cves = client.get("/academy/cves").text
    assert "registro" in cves.lower() or "vulnerabilidade" in cves.lower()
    assert "A logged string containing" not in cves
    with SessionLocal() as db:
        # Seed sanity: every published challenge has hints, a solution and references.
        challenges = db.query(Challenge).all()
        assert len(challenges) >= 31
        for challenge in challenges:
            assert len(challenge.hints) == 3
            assert challenge.solution is not None
            assert challenge.references


def test_dedicated_lab_pages_are_full_screen(session):
    """Each target has its own /lab/<slug> room page, without the dashboard chrome."""
    client = session["client"]

    challenge = client.get("/lab/access-idor-invoices")
    assert challenge.status_code == 200
    assert 'class="lab-mode"' in challenge.text
    assert 'class="lab-topbar"' in challenge.text
    assert '<aside class="sidebar"' not in challenge.text
    # The room page does not link to itself, and its top bar has real exits.
    assert 'href="/lab/access-idor-invoices"' not in challenge.text
    assert 'href="/challenges"' in challenge.text
    assert 'href="/"' in challenge.text
    assert "Página do laboratório" not in challenge.text

    machine = client.get("/lab/machine-meridian-bank")
    assert machine.status_code == 200
    assert 'class="lab-mode"' in machine.text
    assert '<aside class="sidebar"' not in machine.text
    assert ">Máquina<" in machine.text

    # The panel detail view still works and offers the dedicated page.
    panel = client.get("/challenges/access-idor-invoices")
    assert panel.status_code == 200
    assert '<aside class="sidebar"' in panel.text
    assert "Página do laboratório" in panel.text

    # Missing targets are a clean 404, not a stack trace.
    assert client.get("/lab/does-not-exist").status_code == 404


def test_academy_articles_and_filters(session):
    client = session["client"]

    listing = client.get("/academy")
    assert listing.status_code == 200
    assert "Técnica de campo, não folclore" in listing.text
    assert "metodologia" in listing.text.lower()

    for category in (
        "methods", "recon", "auth", "access", "sqli", "xss", "server",
        "api", "logic", "upload", "client", "advanced", "chain", "reference",
    ):
        filtered = client.get("/academy", params={"category": category})
        assert filtered.status_code == 200, category

    for slug in (
        "methodology", "recon", "authentication", "access-control", "sql-injection",
        "xss", "ssrf", "file-inclusion", "command-injection", "api-security",
        "jwt", "business-logic", "client-side", "cache-deception", "file-upload",
        "chaining", "quick-reference",
    ):
        article = client.get(f"/academy/{slug}")
        assert article.status_code == 200, slug
        assert "Nesta página" in article.text
        assert article.text.count("https://") >= 4, f"{slug} needs primary references"

    search = client.get("/academy", params={"q": "JWT"})
    assert search.status_code == 200
    assert "Segurança de JWT" in search.text


def test_profile_export_is_private_and_complete(session):
    client = session["client"]
    export = client.get("/profile/export")
    assert export.status_code == 200
    payload = export.json()
    assert payload["user"]["username"] == USERNAME
    assert payload["xp"] >= 60
    solved = [row for row in payload["progress"] if row["status"] == "completed"]
    assert {row["challenge"] for row in solved} >= {"recon-backup-vault", "ssrf-image-fetcher"}
    assert payload["achievements"]
    assert "RV{" not in export.text
    assert "value" not in export.text.lower()
    assert "password" not in export.text.lower()


def test_settings_and_progress_reset(session):
    client = session["client"]
    csrf = session["csrf"]

    profile = client.post(
        "/settings/profile",
        data={"display_name": "Integration Operator", "_csrf": csrf},
        follow_redirects=False,
    )
    assert profile.status_code == 303
    assert "Integration Operator" in client.get("/profile").text

    wrong = client.post(
        "/settings/reset",
        data={"confirm": "yes", "_csrf": csrf},
        follow_redirects=False,
    )
    assert wrong.status_code == 303
    assert "Frase de confirmação não confere" in client.get("/settings").text

    reset = client.post(
        "/settings/reset",
        data={"confirm": "RESET MY LAB", "_csrf": csrf},
        follow_redirects=False,
    )
    assert reset.status_code == 303
    with SessionLocal() as db:
        user = db.query(User).one()
        assert db.query(Progress).filter_by(user_id=user.id).count() == 0
        assert db.query(ObjectiveState).filter_by(user_id=user.id).count() == 0
