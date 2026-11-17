"""Unified Production Process Runner for Nakama Network.

Runs both the Telegram Bot and the Web Streaming Gateway concurrently in a
single container or VM, managing process lifecycles and graceful shutdowns.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | [RUNNER] %(levelname)-8s | %(message)s",
)
logger = logging.getLogger("runner")

ROOT_DIR = Path(__file__).resolve().parent.parent
PYTHON_EXE = sys.executable


def start_process(module_name: str, name: str) -> subprocess.Popen:
    """Start a python module as a supervised background subprocess."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT_DIR)
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [PYTHON_EXE, "-m", module_name]
    logger.info("Starting %s (%s)...", name, " ".join(cmd))
    return subprocess.Popen(cmd, cwd=str(ROOT_DIR), env=env)


def main() -> None:
    procs: dict[str, subprocess.Popen] = {}
    should_run = True

    def handle_signal(sig, frame):
        nonlocal should_run
        logger.info("Received termination signal (%s). Shutting down all services...", sig)
        should_run = False
        for name, proc in procs.items():
            if proc.poll() is None:
                logger.info("Terminating %s (PID: %s)...", name, proc.pid)
                proc.terminate()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # 1. Start Web Media Streaming Gateway
    procs["web"] = start_process("server.app", "Nakama Web Gateway")
    time.sleep(2)  # Give gateway a moment to initialize database

    # 2. Start Telegram Bot
    procs["bot"] = start_process("bot", "Nakama Telegram Bot")

    logger.info("All services initiated successfully.")

    # Supervise processes
    while should_run:
        time.sleep(2)
        for name, proc in list(procs.items()):
            exit_code = proc.poll()
            if exit_code is not None:
                if not should_run:
                    continue
                logger.warning("Process '%s' exited unexpectedly with code %s. Restarting in 3s...", name, exit_code)
                time.sleep(3)
                mod = "server.app" if name == "web" else "bot"
                procs[name] = start_process(mod, name)

    # Wait for termination
    for name, proc in procs.items():
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Force-killing %s...", name)
            proc.kill()

    logger.info("All services stopped.")


if __name__ == "__main__":
    main()
