# Installation

REDVAULT is a local Python application. It does not require Node.js, Docker or a cloud account. The platform binds to loopback by default, and every lab runs as a separate process on a loopback port.

The application interface and all lab content are written in Brazilian Portuguese (pt-BR); see the language note in [README.md](README.md).

## 1. Prerequisites

| Requirement | Why | Check |
| --- | --- | --- |
| Linux (recommended) | `bubblewrap` and `prlimit` isolation | `uname -a` |
| Python 3.11+ | Application runtime (tested on 3.14) | `python3 --version` |
| pip and venv | Dependency installation | `python3 -m pip --version` |
| `bubblewrap` (recommended) | Read-only system view, private PID namespace, tmpfs | `bwrap --version` |
| `prlimit` (recommended) | Address-space, file-size, file-descriptor limits | `prlimit --version` |
| Chromium + chromedriver (optional) | Real-browser victim for XSS/postMessage/upload labs | `chromedriver --version` |

On Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip \
  bubblewrap util-linux chromium chromium-driver
```

`chromedriver` is expected at `/usr/bin/chromedriver` by default. If yours is elsewhere, set `REDVAULT_CHROMEDRIVER` to the absolute path.

> If `bubblewrap` is unavailable, labs still run under `prlimit` as native processes. That is weaker isolation. Read [SECURITY.md](SECURITY.md) before relying on it.

## 2. Create the environment

```bash
cd /path/to/redvault
python3 -m venv .venv
. .venv/bin/activate

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

The main dependencies are FastAPI, Uvicorn, SQLAlchemy, Jinja2, httpx, PyYAML, Markdown, Flask (inside each lab), and Selenium for the browser bot. Passwords are not used (single local operator), so no password-hashing library is required.

## 3. Start the platform

```bash
python3 run.py
```

Expected:

```text
INFO:     Started server process [...]
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Open **http://127.0.0.1:8000**. On first run:

1. The database and master secret are created under `data/`.
2. The local operator (`operator`) is created automatically; there is no login screen and no password.
3. Challenge and machine manifests are seeded automatically.
4. Use **Challenges → Start lab**, then open the shown `127.0.0.1:<port>` URL.

### Labs and the virtualenv

Labs are spawned with a **system** interpreter (`/usr/bin/python3` by default),
not with `.venv/bin/python3`. This is intentional: when bubblewrap is active the
lab runs inside a sandbox that only binds `/usr`, `/bin`, `/lib`, `/lib64` and
`/etc`, so a venv path such as `.../redvault/.venv/bin/python3` does not exist
inside it. Labs only need the standard library plus Flask.

If you keep Flask installed only inside a virtualenv, or need labs on another
interpreter, point REDVAULT at it explicitly:

```bash
REDVAULT_LAB_PYTHON=/path/to/python3 python3 run.py
```

The chosen interpreter must be able to `import flask`. When it lives outside
the system paths, its prefix is bound into the sandbox automatically.

Everything under `data/` is generated on first start and is ignored by Git. The
repository never ships a database or a master secret, and neither should be
committed to a remote.

The library (Knowledge Base) starts empty except for the 24 documents written for
REDVAULT. Import the external sources on your own machine, from your own clones:

```bash
git clone --depth 1 https://github.com/swisskyrepo/PayloadsAllTheThings /tmp/patt
git clone --depth 1 --branch pt https://github.com/HackTricks-wiki/hacktricks /tmp/hacktricks-pt
python3 scripts/import_kb.py --source payloads-all-the-things --path /tmp/patt --rebuild-index
python3 scripts/import_kb.py --source hacktricks --path /tmp/hacktricks-pt --rebuild-index
```

HackTricks is CC BY-NC 4.0: the import is for non-commercial, attributed use and
stays on your machine (see `/kb/sources` for the licence of every source).

`/login` and `/setup` only redirect to the dashboard. The only session state is a per-browser cookie that carries the CSRF token; **Settings → Rotate session** issues a new token and signs out other browsers. Because there is no authentication, never bind the platform to a non-loopback address (see `REDVAULT_HOST` below).

## 4. Verify

```bash
curl -s http://127.0.0.1:8000/health
# {"ok":true,"app":"redvault","labs":0}
```

Start a lab in the UI and confirm the port is loopback-only:

```bash
ss -ltnp | grep -E ':(8000|420[0-9][0-9])'
```

You should see `127.0.0.1`, not `0.0.0.0` or `::`.

## 5. Configuration

Environment variables are read at process start. Put them in your shell, a local `.env` loader, or a systemd unit. No secrets are required: the master secret is generated on first launch.

| Variable | Default | Meaning |
| --- | --- | --- |
| `REDVAULT_DATA` | `./data` | Database, secret key, lab state and logs |
| `REDVAULT_CONTENT` | `./content` | Academy, paths, tools, glossary, CVE index |
| `REDVAULT_LABS` | `./labs` | Lab implementations and manifests |
| `REDVAULT_HOST` | `127.0.0.1` | Platform bind address. **Do not change without a network security review.** |
| `REDVAULT_OPERATOR` | `operator` | Username recorded for the local operator |
| `REDVAULT_PORT` | `8000` | Platform port |
| `REDVAULT_DB_URL` | `sqlite:///.../data/redvault.db` | SQLAlchemy database URL |
| `REDVAULT_LAB_PORT_START` | `42000` | First lab port |
| `REDVAULT_LAB_PORT_END` | `42999` | Last lab port |
| `REDVAULT_LAB_BIND` | `127.0.0.1` | Interface the labs listen on. `0.0.0.0` lets a second machine on the LAN attack them directly (trusted networks only) |
| `REDVAULT_LAB_PUBLIC_HOST` | empty | Address advertised in lab URLs, e.g. `192.168.1.10` when bound to `0.0.0.0` |
| `REDVAULT_MAX_LABS` | `5` | Concurrent lab processes |
| `REDVAULT_LAB_IDLE_TIMEOUT` | `2700` | Seconds without traffic before a lab is stopped |
| `REDVAULT_LAB_MAX_LIFETIME` | `7200` | Hard limit on a lab's lifetime, regardless of activity |
| `REDVAULT_LAB_START_TIMEOUT` | `15` | Seconds to wait for `/health` |
| `REDVAULT_USE_BWRAP` | `1` | Set `0` to disable bubblewrap |
| `REDVAULT_BOT` | `1` | Enable the Chromium victim |
| `REDVAULT_CHROMEDRIVER` | `/usr/bin/chromedriver` | Chromedriver path |
| `REDVAULT_BOT_TIMEOUT` | `20` | Bot navigation timeout |
| `REDVAULT_DEV` | unset | Enables `/api/docs` (development only) |

Example:

```bash
REDVAULT_PORT=9000 REDVAULT_MAX_LABS=3 python3 run.py
```

Keep `REDVAULT_HOST` at `127.0.0.1`. Changing it can expose intentionally vulnerable applications and the operator interface.

To attack the labs from another computer on the same network, widen **only** the lab range:

```bash
REDVAULT_LAB_BIND=0.0.0.0 REDVAULT_LAB_PUBLIC_HOST=192.168.1.10 python3 run.py
```

The dashboard stays on `127.0.0.1:8000`, and the second machine receives lab URLs like `http://192.168.1.10:42000/`. This is a trusted-network option; read [SECURITY.md](SECURITY.md#opt-in-attacking-the-labs-from-a-second-machine-on-the-lan) before enabling it.

## 6. Running tests

```bash
# Lab exploit tests (each starts a real Flask process on an ephemeral port)
python3 -m pytest tests/test_labs.py -q

# Platform integration tests (isolated temp database, real lab lifecycle)
python3 -m pytest tests/test_platform.py -q

# Full suite
python3 -m pytest -q
```

Platform tests set `REDVAULT_DATA` to a temporary directory before importing the app, set `REDVAULT_BOT=0`, and allocate free ports. They do not modify `data/redvault.db`.

If port `42000` is occupied by a running lab, the manager skips it; tests still allocate another free port in the configured range.

## 7. Optional: run as a user service

Create `~/.config/systemd/user/redvault.service`:

```ini
[Unit]
Description=REDVAULT local lab
After=network.target

[Service]
WorkingDirectory=%h/Projetos/redvault
Environment=REDVAULT_HOST=127.0.0.1
ExecStart=%h/Projetos/redvault/.venv/bin/python run.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now redvault.service
systemctl --user status redvault.service
```

Logs: `journalctl --user -u redvault -f`.

This unit does not add a network namespace or container boundary. It is convenience, not a security sandbox.

## 8. Reset and backup

### Keep flags stable, reset progress

```bash
# Stop the platform first
mv data/redvault.db data/redvault.db.bak
# Keep data/secret.key so previously derived flags do not change.
```

A new database is created on the next start and the local operator is recreated automatically.

### Full clean reset

```bash
# Stop the platform first
rm -rf data/
python3 run.py
```

This removes the database, master secret, lab state and logs. Existing flag values and sessions become invalid.

### Backup

Back up `data/redvault.db` and `data/secret.key`. Without `secret.key`, derived flags cannot be reproduced. The database contains progress and hashed flag submissions; it does not contain raw flag values.

## 9. Troubleshooting

### A lab fails to start

Inspect the per-lab log:

```bash
ls data/labs/logs/
tail -n 80 data/labs/logs/<slug>-<user-id>.log
```

Common causes: missing Flask inside the selected Python, port range exhausted, `bwrap` mount failure, or a syntax error in `labs/<slug>/app.py`.

The API returns a truncated log tail in the error detail; the UI shows a toast.

### `bubblewrap` is not found

```bash
sudo apt install bubblewrap
# or run without it, with weaker isolation:
REDVAULT_USE_BWRAP=0 python3 run.py
```

The Environments page displays the active isolation status.

### Chromium bot fails

```bash
chromedriver --version
chromium --version
```

The major versions must match. Set the correct driver path:

```bash
REDVAULT_CHROMEDRIVER=/usr/bin/chromedriver python3 run.py
```

The bot is only needed for `xss-*`, `client-postmessage`, `upload-svg-avatar` and similar real-browser labs. The platform and other labs work without it.

### `database is locked`

SQLite allows one writer. Do not run two REDVAULT platform processes against the same `REDVAULT_DATA`. Stop the duplicate, or give each instance its own data directory.

### Ports are exhausted

Only five labs run by default. Stop unused labs from **Environments**, or adjust `REDVAULT_MAX_LABS` and the port range. Do not widen the range into ports used by other services.

### Styles or JavaScript do not load

Hard-refresh (`Ctrl+Shift+R`). Static files are served from `/static`; a reverse proxy that rewrites paths will break absolute asset URLs. REDVAULT is not designed to run behind one.

### Password lost

Stop the platform and remove/replace `data/redvault.db` as described above. There is no email recovery.

## 10. Upgrading

```bash
# Stop the platform
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 run.py
```

Schema creation is additive via SQLAlchemy's `create_all`; this project does not yet include migrations. Back up `data/` before upgrading. Content is re-seeded from manifests on every start, so new labs appear automatically.
