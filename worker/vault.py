"""Saved logins, keyed by EXACT origin. Values are handed to Playwright directly and never shown to Claude.

Milestone 2: test logins for the mock sites, read from env. Milestone 3 moves this to an encrypted
vault in the orchestrator.
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Vault:
    def __init__(self):
        port = os.getenv("MOCK_PORT", "8100")
        self._entries = {
            f"http://maplebank.localhost:{port}": ("MOCK_BANK_USER", "MOCK_BANK_PASS"),
            f"http://mail.localhost:{port}": ("MOCK_MAIL_USER", "MOCK_MAIL_PASS"),
        }

    def origins(self):
        return list(self._entries)

    def get(self, origin):
        keys = self._entries.get(origin)
        if not keys:
            return None
        user, pw = os.getenv(keys[0]), os.getenv(keys[1])
        return (user, pw) if user and pw else None
