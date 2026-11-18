"""Lifecycle manager for isolated vulnerable labs.

Each lab runs in its own process, bound to 127.0.0.1 on a dedicated port. When
bubblewrap is available (default), the process gets a read-only system view, a
private PID namespace, no access to the user's home directory and only a
writable /state directory. This is not a substitute for Docker, but it keeps
intentionally vulnerable code away from personal files on this host.

Labs bind to loopback unless ``REDVAULT_LAB_BIND`` explicitly widens that (for
example ``0.0.0.0`` to let a second machine on a trusted LAN attack the lab
directly). All flags are injected per process and validated by the platform,
not by the lab.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .config import (
    DATA_DIR,
    LAB_BIND,
    LAB_IDLE_TIMEOUT,
    LAB_MAX_LIFETIME,
    LAB_PUBLIC_HOST,
    LAB_PORT_END,
    LAB_PORT_START,
    LAB_START_TIMEOUT,
    LABS_DIR,
    MAX_ACTIVE_LABS,
    PORT as PLATFORM_PORT,
    USE_BWRAP,
)
from .flags import derive_flag
from .security import sha256
from .models import Challenge, LabSession, ObjectiveState, User


class LabError(RuntimeError):
    pass


def lan_share_enabled() -> bool:
    """Labs are reachable from other machines only when the bind was widened."""
    return LAB_PUBLIC_HOST != "" or LAB_BIND not in ("127.0.0.1", "::1")


def lab_url(port: int) -> str:
    """Address a browser on this host (or on a LAN client) can reach the lab."""
    host = LAB_PUBLIC_HOST or ("127.0.0.1" if LAB_BIND in ("0.0.0.0", "::") else LAB_BIND)
    return f"http://{host}:{port}/"


@dataclass
class ActiveLab:
    session_id: int
    challenge_id: int
    user_id: int
    port: int
    token: str
    process: subprocess.Popen
    state_dir: Path
    log_path: Path
    started_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)


class LabManager:
    def __init__(self) -> None:
        self._labs: dict[int, ActiveLab] = {}
        self._ports: set[int] = set()
        self._lock = threading.RLock()
        self._reaper_started = False

    # -- helpers ---------------------------------------------------------
    def _alloc_port(self) -> int:
        with self._lock:
            for port in range(LAB_PORT_START, LAB_PORT_END + 1):
                if port in self._ports or port == PLATFORM_PORT:
                    continue
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        sock.bind((LAB_BIND, port))
                    except OSError:
                        continue
                self._ports.add(port)
                return port
        raise LabError("no free lab port available")

    def _release_port(self, port: int) -> None:
        with self._lock:
            self._ports.discard(port)

    def _bwrap_available(self) -> bool:
        return bool(USE_BWRAP and shutil.which("bwrap"))

    def _lab_python(self) -> str:
        """Interpreter used to spawn labs.

        Labs must not inherit the platform's virtualenv. When the platform is
        started from an activated `.venv`, `shutil.which("python3")` resolves to
        `.venv/bin/python3`, which lives *outside* the bwrap sandbox (only
        /usr, /bin, /lib, /lib64 and /etc are bound). The sandbox then fails
        with `bwrap: execvp .venv/bin/python3: No such file or directory`.

        Instead, prefer a system interpreter. The labs only need the standard
        library plus Flask, so a system python that can import Flask beats a
        venv python that the sandbox cannot see. If no system candidate works,
        fall back to the current interpreter (un-sandboxed `sys.executable`),
        which may still be the venv one; `_venv_bindable()` covers that case.
        """
        candidates = [
            os.environ.get("REDVAULT_LAB_PYTHON", ""),
            "/usr/bin/python3",
            "/usr/local/bin/python3",
            "/bin/python3",
        ]
        for candidate in candidates:
            if not candidate or not os.path.exists(candidate):
                continue
            if self._python_has_flask(candidate):
                return candidate
            resolved = os.path.realpath(candidate)
            if resolved != candidate and os.path.exists(resolved) and self._python_has_flask(resolved):
                # e.g. a broken/rebuilt `.venv` symlink pointing at a system
                # interpreter that does have Flask installed.
                return resolved
        # Last resort: the interpreter running the platform. If it is a venv
        # interpreter the sandbox binds it explicitly (see _build_command).
        return sys.executable

    @staticmethod
    def _python_has_flask(python: str) -> bool:
        try:
            result = subprocess.run(
                [python, "-c", "import flask"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def _venv_bindable(self, python: str) -> str | None:
        """Return a venv prefix that must be bound into the sandbox, if any.

        Only relevant when the chosen interpreter is NOT a system one (Flask
        exists only inside `.venv`). The prefix has to be visible inside bwrap
        for the venv's `site-packages` to be found.
        """
        system_prefixes = ("/usr/", "/bin/", "/sbin/")
        if python.startswith(system_prefixes):
            return None
        try:
            result = subprocess.run(
                [python, "-c", "import sys; print(sys.prefix)"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        prefix = result.stdout.strip()
        if not prefix or prefix in ("/usr", "/usr/local", "/"):
            return None
        return prefix

    def _build_command(self, lab_dir: Path, state_dir: Path, env: dict) -> list[str]:
        python = self._lab_python()
        if not self._bwrap_available():
            inner = [python, str(lab_dir / "app.py")]
        else:
            binds = ["/usr", "/bin", "/lib", "/lib64", "/etc"]
            venv_prefix = self._venv_bindable(python)
            if venv_prefix and os.path.exists(venv_prefix):
                # Bind the real venv prefix (resolving symlinks such as
                # `.venv/bin/python3 -> /usr/bin/python3`) so a venv-only Flask
                # installation keeps working under bwrap.
                binds.append(venv_prefix)
            args = ["bwrap"]
            for path in binds:
                if os.path.exists(path):
                    args += ["--ro-bind", path, path]
            args += [
                "--ro-bind", str(lab_dir), "/lab",
                "--ro-bind", str(LABS_DIR / "_shared"), "/shared",
                "--bind", str(state_dir), "/state",
                "--tmpfs", "/tmp",
                "--tmpfs", "/run",
                "--proc", "/proc",
                "--dev", "/dev",
                "--unshare-pid",
                "--new-session",
                "--die-with-parent",
                "--chdir", "/lab",
            ]
            for key, value in env.items():
                args += ["--setenv", key, value]
            args += [python, "/lab/app.py"]
            inner = args
        prlimit = shutil.which("prlimit")
        if prlimit:
            return [
                prlimit,
                "--core=0",
                "--as=805306368",
                "--nofile=512",
                "--fsize=67108864",
                "--",
                *inner,
            ]
        return inner

    def _base_env(self, port: int, lab: ActiveLab | None = None, challenge: Challenge | None = None, user_id: int = 0) -> dict:
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LAB_PORT": str(port),
            "LAB_BIND": LAB_BIND,
            "LAB_STATE_DIR": "/state",
            "LAB_CALLBACK_URL": f"http://127.0.0.1:{PLATFORM_PORT}/internal/lab-callback",
            "LAB_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
        }
        if lab is not None:
            env["LAB_CALLBACK_TOKEN"] = lab.token
            env["LAB_SESSION_ID"] = str(lab.session_id)
        if challenge is not None:
            env["LAB_CHALLENGE_SLUG"] = challenge.slug
            env["LAB_CHALLENGE_ID"] = str(challenge.id)
            env["LAB_FLAGS"] = json.dumps(
                {flag.key: derive_flag(challenge.slug, flag.key) for flag in challenge.flags}
            )
        if user_id:
            env["LAB_USER_ID"] = str(user_id)
        return env

    # -- public API ------------------------------------------------------
    def reconcile_startup(self) -> None:
        from .database import db_session

        with db_session() as db:
            db.execute(update(LabSession).where(LabSession.status.in_(["running", "starting"])).values(status="stopped"))
        self._start_reaper()

    def active_for(self, user_id: int, challenge_id: int) -> ActiveLab | None:
        with self._lock:
            # Snapshot: a concurrent start/stop mutates the dict and a live view
            # raises "dictionary changed size during iteration", which 500'd the
            # whole platform during a lab launch.
            for lab in list(self._labs.values()):
                if lab.user_id == user_id and lab.challenge_id == challenge_id:
                    if lab.process.poll() is None:
                        return lab
                    self._labs.pop(lab.session_id, None)
            return None

    def get(self, session_id: int) -> ActiveLab | None:
        with self._lock:
            lab = self._labs.get(session_id)
            if lab and lab.process.poll() is None:
                return lab
            if lab:
                self._labs.pop(session_id, None)
            return None

    def lab_on_port(self, port: int) -> ActiveLab | None:
        with self._lock:
            for lab in list(self._labs.values()):
                if lab.port == port and lab.process.poll() is None:
                    return lab
            return None

    def touch_port(self, port: int) -> None:
        """Mark a lab as active because real traffic reached it."""
        lab = self.lab_on_port(port)
        if lab is not None:
            lab.last_active = time.time()

    def active_labs(self) -> list[ActiveLab]:
        with self._lock:
            alive = []
            for sid, lab in list(self._labs.items()):
                if lab.process.poll() is None:
                    alive.append(lab)
                else:
                    self._labs.pop(sid, None)
            return alive

    def start(self, db: Session, user: User, challenge: Challenge) -> LabSession:
        existing = self.active_for(user.id, challenge.id)
        if existing:
            row = db.get(LabSession, existing.session_id)
            if row:
                return row
        if len(self.active_labs()) >= MAX_ACTIVE_LABS:
            raise LabError(f"maximum of {MAX_ACTIVE_LABS} active labs reached; stop one first")
        lab_dir = LABS_DIR / challenge.lab_dir
        if not (lab_dir / "app.py").exists():
            raise LabError(f"lab implementation missing: {challenge.lab_dir}/app.py")

        port = self._alloc_port()
        token = os.urandom(32).hex()
        state_dir = DATA_DIR / "labs" / "state" / f"{challenge.slug}-{user.id}-{int(time.time())}"
        # One directory per *session*, not per second: two labs of the same
        # challenge started within the same second used to share a state dir,
        # so the second run overwrote the first run's log and its capture.
        if state_dir.exists():
            state_dir = state_dir.with_name(f"{state_dir.name}-{uuid.uuid4().hex[:6]}")
        state_dir.mkdir(parents=True, exist_ok=True)
        log_path = DATA_DIR / "labs" / "logs" / f"{challenge.slug}-{user.id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # The row must exist before the lab starts: the lab gets its token and
        # session id from the environment and cannot report objectives without
        # them. A placeholder row (session_id 0) would leave LAB_SESSION_ID=0
        # and every `lab.objective()` call would be rejected.
        row = LabSession(
            challenge_id=challenge.id,
            user_id=user.id,
            port=port,
            pid=0,
            token_hash=sha256(token),
            state_dir=str(state_dir),
            status="starting",
            started_at=datetime.now(timezone.utc),
            last_active=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        placeholder = ActiveLab(
            session_id=row.id, challenge_id=challenge.id, user_id=user.id, port=port,
            token=token, process=None, state_dir=state_dir, log_path=log_path,  # type: ignore[arg-type]
        )
        env = self._base_env(port, placeholder, challenge, user.id)
        # The sandbox binds the state dir at /state; without bwrap the lab needs
        # the real path or its log/database drift to /tmp.
        env["LAB_STATE_DIR"] = "/state" if self._bwrap_available() else str(state_dir)
        env["PYTHONPATH"] = "/shared" if self._bwrap_available() else str(LABS_DIR / "_shared")
        # Keep the lab's diagnostics where the operator can find them: inside the
        # sandboxed run stderr/print go to /state/lab.log instead of the platform
        # service log (started by systemd/nohup, or closed).
        if self._bwrap_available():
            env["LAB_LOG_FILE"] = "/state/lab.log"
        command = self._build_command(lab_dir, state_dir, env)

        log = log_path.open("ab")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(lab_dir),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            log.close()
            self._release_port(port)
            row.status = "failed"
            row.error = f"unable to spawn lab: {exc}"[:500]
            db.commit()
            raise LabError(f"unable to spawn lab: {exc}") from exc
        finally:
            try:
                log.close()
            except Exception:
                pass

        row.pid = process.pid
        db.commit()
        active = ActiveLab(
            session_id=row.id,
            challenge_id=challenge.id,
            user_id=user.id,
            port=port,
            token=token,
            process=process,
            state_dir=state_dir,
            log_path=log_path,
        )
        with self._lock:
            self._labs[row.id] = active

        if not self._wait_ready(port, process, log_path):
            self.stop(db, row, clear_objectives=False)
            raise LabError(self._log_tail(log_path) or "lab failed to become ready")
        row.status = "running"
        db.commit()
        self._start_reaper()
        return row

    def _wait_ready(self, port: int, process: subprocess.Popen, log_path: Path) -> bool:
        deadline = time.time() + LAB_START_TIMEOUT
        while time.time() < deadline:
            if process.poll() is not None:
                return False
            probe_host = "127.0.0.1" if LAB_BIND in ("0.0.0.0", "::") else LAB_BIND
            try:
                response = httpx.get(f"http://{probe_host}:{port}/health", timeout=0.6)
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        return False

    def _log_tail(self, log_path: Path, lines: int = 12) -> str:
        try:
            content = log_path.read_text(errors="replace").splitlines()[-lines:]
            return "\n".join(content)[-1200:]
        except OSError:
            return ""

    def _terminate(self, lab: ActiveLab) -> None:
        try:
            os.killpg(os.getpgid(lab.process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            lab.process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(lab.process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                lab.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        self._release_port(lab.port)

    def stop(self, db: Session, row: LabSession, clear_objectives: bool = False) -> None:
        with self._lock:
            lab = self._labs.pop(row.id, None)
        if lab:
            self._terminate(lab)
        row.status = "stopped"
        if clear_objectives:
            db.execute(
                delete(ObjectiveState).where(
                    ObjectiveState.user_id == row.user_id,
                    ObjectiveState.challenge_id == row.challenge_id,
                )
            )
        db.commit()
        try:
            shutil.rmtree(row.state_dir, ignore_errors=True)
        except OSError:
            pass

    def stop_user_challenge(self, db: Session, user_id: int, challenge_id: int, clear_objectives: bool = False) -> bool:
        rows = db.scalars(
            select(LabSession).where(
                LabSession.user_id == user_id,
                LabSession.challenge_id == challenge_id,
                LabSession.status.in_(["running", "starting"]),
            )
        ).all()
        for row in rows:
            self.stop(db, row, clear_objectives=clear_objectives)
        return bool(rows)

    def reset(self, db: Session, user: User, challenge: Challenge) -> LabSession:
        old = db.scalar(
            select(LabSession).where(
                LabSession.user_id == user.id,
                LabSession.challenge_id == challenge.id,
                LabSession.status.in_(["running", "starting"]),
            ).order_by(LabSession.id.desc())
        )
        previous_resets = old.reset_count if old else 0
        if old:
            self.stop(db, old, clear_objectives=True)
        row = self.start(db, user, challenge)
        row.reset_count = previous_resets + 1
        db.commit()
        return row

    def touch(self, session_id: int) -> None:
        lab = self.get(session_id)
        if lab:
            lab.last_active = time.time()

    def shutdown(self) -> None:
        with self._lock:
            labs = list(self._labs.values())
        for lab in labs:
            self._terminate(lab)
        self._labs.clear()

    def _start_reaper(self) -> None:
        if self._reaper_started:
            return
        self._reaper_started = True

        def reap() -> None:
            while True:
                time.sleep(60)
                try:
                    self._reap_once()
                except Exception:
                    pass

        thread = threading.Thread(target=reap, name="lab-reaper", daemon=True)
        thread.start()

    def _reap_once(self) -> None:
        from .database import db_session

        now = time.time()
        for lab in self.active_labs():
            expired = now - lab.started_at > LAB_MAX_LIFETIME
            idle = now - lab.last_active > LAB_IDLE_TIMEOUT
            if expired or idle:
                with db_session() as db:
                    row = db.get(LabSession, lab.session_id)
                    if row:
                        self.stop(db, row)
                        row.error = "stopped after idle timeout"
                        db.commit()


lab_manager = LabManager()
