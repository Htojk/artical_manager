"""Start the local backend and frontend without relying on PowerShell scripts.

Some Windows machines block unsigned PowerShell scripts, which made the old
start.bat exit immediately. This launcher only needs the Python runtime that
the project already uses and keeps the console open while both services run.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
LOG_DIR = ROOT / "logs"
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
BACKEND_LOG = LOG_DIR / "backend.out.log"
BACKEND_ERR = LOG_DIR / "backend.err.log"
FRONTEND_LOG = LOG_DIR / "frontend.out.log"
FRONTEND_ERR = LOG_DIR / "frontend.err.log"


def _env_value(key: str, default: str) -> str:
    value = os.environ.get(key)
    if value and value.strip():
        return value.strip()
    env_file = ROOT / ".env"
    if env_file.exists():
        try:
            lines = env_file.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            lines = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, item = line.split("=", 1)
            if name.strip() == key:
                return item.strip().strip('"').strip("'")
    return default


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


def _wait_http_ok(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if getattr(response, "status", 200) == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _wait_port(port: int, timeout: float, host: str = "127.0.0.1") -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_in_use(port, host):
            return True
        time.sleep(0.5)
    return False


def _tail(path: Path, lines: int = 20) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(日志文件尚不存在)"
    return "\n".join(content[-lines:]) or "(空)"


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _start_process(command: list[str], cwd: Path, out, err) -> subprocess.Popen:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=out,
        stderr=err,
        env=env,
        creationflags=flags,
    )


def main() -> int:
    # Chinese Windows consoles default to GBK; Vite's log contains characters
    # such as "➜" that GBK cannot encode. Never let diagnostics crash the
    # launcher while reporting a startup failure.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="启动 Article Autopilot 前后端")
    parser.add_argument("--no-browser", action="store_true", help="启动后不打开浏览器")
    args = parser.parse_args()

    if not VENV_PYTHON.exists():
        print("未找到 .venv，请先运行：")
        print(r"  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1")
        print("如果 PowerShell 被系统策略阻止，请参考 README 手动安装依赖。")
        return 1
    if not (FRONTEND / "node_modules").exists():
        print("未安装前端依赖，请先运行：")
        print(r"  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1")
        return 1
    if not shutil.which("npm.cmd" if os.name == "nt" else "npm"):
        print("未找到 npm，请安装 Node.js 18+ 并加入 PATH。")
        return 1

    backend_port = int(_env_value("APP_PORT", "8000"))
    frontend_port = int(_env_value("APP_FRONTEND_PORT", "5173"))
    if backend_port == frontend_port:
        print("APP_PORT 与 APP_FRONTEND_PORT 不能相同。")
        return 1

    busy = [
        name
        for name, port in (("后端", backend_port), ("前端", frontend_port))
        if _port_in_use(port)
    ]
    if busy:
        print(f"{'、'.join(busy)}端口已被占用，请先停止旧进程或修改 .env 中的端口。")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    backend_out = open(BACKEND_LOG, "wb")
    backend_err = open(BACKEND_ERR, "wb")
    frontend_out = open(FRONTEND_LOG, "wb")
    frontend_err = open(FRONTEND_ERR, "wb")
    backend: subprocess.Popen | None = None
    frontend: subprocess.Popen | None = None

    try:
        print(f"启动后端 http://127.0.0.1:{backend_port} ...", flush=True)
        backend = _start_process(
            [
                str(VENV_PYTHON),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(backend_port),
            ],
            BACKEND,
            backend_out,
            backend_err,
        )

        print(f"启动前端 http://127.0.0.1:{frontend_port} ...", flush=True)
        frontend = _start_process(
            [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/c",
                "npm.cmd" if os.name == "nt" else "npm",
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(frontend_port),
                "--strictPort",
            ],
            FRONTEND,
            frontend_out,
            frontend_err,
        )

        if not _wait_http_ok(f"http://127.0.0.1:{backend_port}/api/health", timeout=60):
            print("\n后端启动失败，最近日志：")
            print(_tail(BACKEND_ERR))
            return 1

        if frontend.poll() is not None or not _wait_port(frontend_port, timeout=45):
            print("\n前端启动失败，最近日志：")
            print(_tail(FRONTEND_ERR))
            print(_tail(FRONTEND_LOG))
            return 1

        print("服务已就绪。", flush=True)
        print(f"  前端：http://127.0.0.1:{frontend_port}")
        print(f"  后端：http://127.0.0.1:{backend_port}/api/health")
        print(f"  日志：{LOG_DIR}")
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{frontend_port}")
        print("\n按 Enter 停止前后端（或按 Ctrl+C）...", flush=True)
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        return 0
    finally:
        print("正在停止服务...", flush=True)
        _stop(frontend)
        _stop(backend)
        for handle in (backend_out, backend_err, frontend_out, frontend_err):
            handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
