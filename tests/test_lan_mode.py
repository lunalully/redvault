"""LAN sharing mode: a lab started with REDVAULT_LAB_BIND widened must be
reachable from another address, not only from 127.0.0.1.

The test boots a real lab process through the real manager and talks to it over
the host's non-loopback address, which is what a second computer on the same
network would use. Everything runs in a temporary data directory.
"""
from __future__ import annotations

import atexit
import os
import shutil
import socket
import tempfile

import pytest

_TEST_DATA = tempfile.mkdtemp(prefix="redvault-lan-test-")
os.environ["REDVAULT_DATA"] = _TEST_DATA
os.environ.setdefault("REDVAULT_BOT", "0")
os.environ["REDVAULT_LAB_BIND"] = "0.0.0.0"
os.environ.setdefault("REDVAULT_LAB_START_TIMEOUT", "25")
atexit.register(lambda: shutil.rmtree(_TEST_DATA, ignore_errors=True))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import LAB_BIND  # noqa: E402
from app.main import app  # noqa: E402


def _lan_address() -> str | None:
    """Find a non-loopback IPv4 address of this host, without sending packets."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # documentation range, no route needed
            address = sock.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") else address


LAN = _lan_address()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _csrf(client: TestClient) -> str:
    import re

    page = client.get("/lab/access-idor-invoices").text
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
    assert match, "CSRF meta tag missing"
    return match.group(1)


def test_lab_binds_to_the_configured_interface(client):
    assert LAB_BIND == "0.0.0.0"
    started = client.post(
        "/api/challenges/access-idor-invoices/start",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert started.status_code == 200, started.text
    payload = started.json()
    assert payload["active"] is True
    port = payload["port"]
    try:
        import httpx

        # What the second machine does: hit the lab on the host's LAN address.
        probe = LAN or "127.0.0.1"
        response = httpx.get(f"http://{probe}:{port}/health", timeout=5)
        assert response.status_code == 200
        assert response.json()["ok"] is True
        if LAN:
            # The vulnerable app itself, from a non-loopback address.
            home = httpx.get(f"http://{LAN}:{port}/", timeout=5)
            assert home.status_code == 200
            assert "lan shared" in home.text.lower()
    finally:
        client.post(
            "/api/challenges/access-idor-invoices/stop",
            headers={"X-CSRF-Token": _csrf(client)},
        )


def test_lab_page_advertises_lan_address(client):
    page = client.get("/lab/access-idor-invoices").text
    assert "aceita conexões da sua rede local" in page
    assert "lab-lan-note" in page

def test_default_mode_keeps_the_range_on_loopback():
    """Without the opt-in, the port must not answer on the LAN address."""
    if not LAN:
        pytest.skip("no non-loopback address to probe")
    from app import lab_manager as lm

    original = lm.LAB_BIND
    lm.LAB_BIND = "127.0.0.1"
    try:
        port = lm.lab_manager._alloc_port()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", port))
                sock.listen(1)
                import httpx

                with pytest.raises(httpx.ConnectError):
                    httpx.get(f"http://{LAN}:{port}/health", timeout=2)
        finally:
            lm.lab_manager._release_port(port)
    finally:
        lm.LAB_BIND = original


def test_lab_never_uses_the_platform_venv_outside_the_sandbox(tmp_path):
    """Regression: starting from an activated `.venv` broke "start lab".

    `shutil.which("python3")` resolved to `.venv/bin/python3`, which bwrap
    cannot see (only /usr, /bin, /lib, /lib64 and /etc are bound), so every lab
    launch failed with
    "bwrap: execvp /path/redvault/.venv/bin/python3: No such file or directory".
    """
    from app.lab_manager import lab_manager

    # Simulate the activated-venv ordering of PATH that triggered the bug.
    fake_venv = tmp_path / ".venv" / "bin"
    fake_venv.mkdir(parents=True)
    (fake_venv / "python3").symlink_to("/usr/bin/python3")
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{fake_venv}:{old_path}"
    try:
        python = lab_manager._lab_python()
    finally:
        os.environ["PATH"] = old_path

    assert ".venv" not in python, python
    assert os.path.isabs(python) and os.path.exists(python)

    command = lab_manager._build_command(
        tmp_path, tmp_path / "state", {"LAB_PORT": "0"}
    )
    assert str(fake_venv) not in " ".join(command)
