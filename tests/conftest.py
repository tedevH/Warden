"""Shared test setup: mock sites on a test port, a throwaway vault, and an isolated database."""
import asyncio
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

PORT = 8199
os.environ["MOCK_PORT"] = str(PORT)          # must be set before mocksites/worker are imported
os.environ["CHERT_MODE"] = "mock"
os.environ["LEND_DB"] = ":memory:"

import pytest  # noqa: E402
import uvicorn  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

from mocksites.app import app, reset_all  # noqa: E402
from mocksites.seed import creds  # noqa: E402
from orchestrator.vault import Vault  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def mock_server():
    socks = []
    for fam, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        s = socket.socket(fam, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if fam == socket.AF_INET6:
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        s.bind((host, PORT))
        socks.append(s)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    t = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=socks)), daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield
    server.should_exit = True
    t.join(5)


@pytest.fixture(autouse=True)
def fresh():
    reset_all()


def make_vault():
    v = Vault(Path(tempfile.mkdtemp()) / "vault.enc", Fernet.generate_key().decode())
    v.put(f"http://maplebank.localhost:{PORT}", *creds("bank"))
    v.put(f"http://mail.localhost:{PORT}", *creds("mail"))
    return v


@pytest.fixture
def vault():
    return make_vault()
