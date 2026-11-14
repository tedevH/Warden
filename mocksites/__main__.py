"""Serve the mock sites on both loopback addresses (127.0.0.1 and ::1), never on the network.

    python -m mocksites
"""
import asyncio
import os
import socket

import uvicorn
from dotenv import load_dotenv

load_dotenv()


def _sock(family, host, port):
    s = socket.socket(family, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if family == socket.AF_INET6:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    s.bind((host, port))
    return s


def main():
    port = int(os.getenv("MOCK_PORT", "8100"))
    socks = [_sock(socket.AF_INET, "127.0.0.1", port)]
    try:
        socks.append(_sock(socket.AF_INET6, "::1", port))
    except OSError:
        pass  # no IPv6 loopback
    print(f"Mock sites on http://localhost:{port} (admin) and http://<site>.localhost:{port}", flush=True)
    server = uvicorn.Server(uvicorn.Config("mocksites.app:app", log_level="warning"))
    asyncio.run(server.serve(sockets=socks))


if __name__ == "__main__":
    main()
