"""Encrypted credential vault. Logins are keyed by EXACT origin and only ever handed to Playwright.

    python -m orchestrator.vault init         # create the key in .env if missing, then seed-mocks
    python -m orchestrator.vault key          # print a new LEND_VAULT_KEY for .env
    python -m orchestrator.vault seed-mocks   # store the mock-site test logins (from .env) in the vault
    python -m orchestrator.vault list         # origins only, never values

File: data/vault.enc (Fernet, key from LEND_VAULT_KEY). Without a key or file, the vault is empty,
so Warden can't sign in anywhere.
"""
import json
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
VAULT_FILE = Path(os.getenv("LEND_VAULT_FILE", ROOT / "data" / "vault.enc"))


class Vault:
    def __init__(self, path: Path = VAULT_FILE, key: str | None = None):
        self.path = Path(path)
        key = key or os.getenv("LEND_VAULT_KEY", "")
        self._f = Fernet(key.encode()) if key else None
        self._entries = self._load()

    def _load(self):
        if not self._f or not self.path.exists():
            return {}
        try:
            return json.loads(self._f.decrypt(self.path.read_bytes()))
        except InvalidToken:
            raise SystemExit("LEND_VAULT_KEY does not match data/vault.enc")

    def _save(self):
        if not self._f:
            raise RuntimeError("Set LEND_VAULT_KEY first (python -m orchestrator.vault key)")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self._f.encrypt(json.dumps(self._entries).encode()))
        os.chmod(self.path, 0o600)

    def origins(self):
        return list(self._entries)

    def get(self, origin):
        e = self._entries.get(origin.lower())
        return (e["username"], e["password"]) if e else None

    def put(self, origin, username, password):
        self._entries[origin.lower()] = {"username": username, "password": password}
        self._save()


def _main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "key":
        print(Fernet.generate_key().decode())
    elif cmd == "init":
        env = ROOT / ".env"
        text = env.read_text() if env.exists() else ""
        if not os.getenv("LEND_VAULT_KEY"):
            key = Fernet.generate_key().decode()
            lines = [l for l in text.splitlines() if not l.startswith("LEND_VAULT_KEY=")]
            env.write_text("\n".join(lines + [f"LEND_VAULT_KEY={key}"]) + "\n")
            os.environ["LEND_VAULT_KEY"] = key
            print("Created LEND_VAULT_KEY in .env")
        sys.argv[1] = "seed-mocks"
        return _main()
    elif cmd == "seed-mocks":
        port = os.getenv("MOCK_PORT", "8100")
        v = Vault()
        for host, u, p in (("maplebank.localhost", "MOCK_BANK_USER", "MOCK_BANK_PASS"),
                           ("mail.localhost", "MOCK_MAIL_USER", "MOCK_MAIL_PASS")):
            if not (os.getenv(u) and os.getenv(p)):
                sys.exit(f"{u}/{p} missing from .env")
            v.put(f"http://{host}:{port}", os.environ[u], os.environ[p])
        print("Saved test logins for:", ", ".join(v.origins()))
    elif cmd == "list":
        print("\n".join(Vault().origins()) or "(empty)")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    _main()
