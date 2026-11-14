"""Tamper-evident action log, anchored on Solana.

An AI that touches your money should not be able to rewrite its own history. So:

  1. Every row in the action log is fingerprinted into a hash chain:
         hash[n] = sha256(hash[n-1] + the row's contents)
     Changing or deleting any earlier row changes every fingerprint after it.
  2. Every few seconds the newest fingerprint (the chain head) is written to Solana in a Memo transaction.
     One cheap transaction therefore commits to the whole log up to that point.
  3. Verifying recomputes the chain from the database and compares it with what Solana holds. Whoever edits the
     database (a thief, a bug, or Warden itself) cannot also edit Solana, so the edit shows.

Only fingerprints go on chain: no emails, amounts, addresses or names.

Setup:  make solana        creates a devnet wallet in data/ (gitignored) and asks the devnet faucet for test SOL
Config: SOLANA_RPC (default: devnet), LEND_CHAIN=off to disable. Without a wallet file it stays off.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
from pathlib import Path

import httpx

log = logging.getLogger("lend.chain")
ROOT = Path(__file__).resolve().parents[1]
WALLET = Path(os.getenv("SOLANA_WALLET", str(ROOT / "data" / "solana-wallet.json")))
RPC = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")
MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
GENESIS = "0" * 64
COLS = ("id", "ts", "task_id", "kind", "url", "element", "classification", "tier", "decision", "reason")
SCHEMA = """CREATE TABLE IF NOT EXISTS anchors (
  action_id INTEGER PRIMARY KEY, hash TEXT NOT NULL, sig TEXT);"""


def cluster():
    return "devnet" if "devnet" in RPC else "testnet" if "testnet" in RPC else "mainnet-beta"


def explorer(sig):
    return f"https://explorer.solana.com/tx/{sig}?cluster={cluster()}"


def row_hash(prev: str, row: dict) -> str:
    body = json.dumps([row[c] for c in COLS], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def memo_text(last_id: int, head: str) -> str:
    return f"warden-log v1 #{last_id} {head}"


def enabled():
    return os.getenv("LEND_CHAIN", "on") != "off" and WALLET.exists()


# ---------------- Solana JSON-RPC (plain HTTP; solders only signs) ----------------
def _rpc(method, params, timeout=20.0):
    r = httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout)
    r.raise_for_status()
    out = r.json()
    if out.get("error"):
        raise RuntimeError(f"{method}: {out['error'].get('message', out['error'])}")
    return out["result"]


def load_wallet():
    from solders.keypair import Keypair
    return Keypair.from_bytes(bytes(json.loads(WALLET.read_text())))


def create_wallet():
    from solders.keypair import Keypair
    if not WALLET.exists():
        WALLET.parent.mkdir(parents=True, exist_ok=True)
        WALLET.write_text(json.dumps(list(bytes(Keypair()))))
        WALLET.chmod(0o600)
    return load_wallet()


def balance(pubkey) -> float:
    return _rpc("getBalance", [str(pubkey)])["value"] / 1e9


def send_memo(text: str) -> str:
    """Write `text` to Solana in one Memo transaction. Returns the transaction signature."""
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction
    kp = load_wallet()
    blockhash = Hash.from_string(_rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
    ix = Instruction(Pubkey.from_string(MEMO_PROGRAM), text.encode(), [AccountMeta(kp.pubkey(), True, True)])
    tx = Transaction([kp], Message.new_with_blockhash([ix], kp.pubkey(), blockhash), blockhash)
    return _rpc("sendTransaction", [base64.b64encode(bytes(tx)).decode(),
                                    {"encoding": "base64", "preflightCommitment": "confirmed"}])


def read_memo(sig: str) -> str | None:
    """The memo text of a confirmed transaction, or None if Solana doesn't have it (yet)."""
    tx = _rpc("getTransaction", [sig, {"encoding": "jsonParsed", "commitment": "confirmed",
                                       "maxSupportedTransactionVersion": 0}])
    if not tx:
        return None
    for ix in tx["transaction"]["message"]["instructions"]:
        if ix.get("programId") == MEMO_PROGRAM:
            return ix.get("parsed")
    return None


# ---------------- the chain ----------------
class Chain:
    def __init__(self, store):
        self.store = store
        self.store._exec(SCHEMA)
        self.last_error = None

    def _rows(self):
        return self.store._all("SELECT * FROM actions ORDER BY id")

    def extend(self):
        """Fingerprint any action rows that don't have one yet. Returns how many were added."""
        done = {r["action_id"]: r["hash"] for r in self.store._all("SELECT action_id, hash FROM anchors")}
        prev, added = GENESIS, 0
        for row in self._rows():
            if row["id"] in done:
                prev = done[row["id"]]
                continue
            prev = row_hash(prev, row)
            self.store._exec("INSERT INTO anchors (action_id, hash) VALUES (?, ?)", (row["id"], prev))
            added += 1
        return added

    def pending(self):
        return self.store._all("SELECT action_id, hash FROM anchors WHERE sig IS NULL ORDER BY action_id")

    def checkpoint(self):
        """Anchor the chain head on Solana, covering every fingerprint not yet anchored. Returns the signature."""
        self.extend()
        todo = self.pending()
        if not todo:
            return None
        last = todo[-1]
        sig = send_memo(memo_text(last["action_id"], last["hash"]))
        self.store._exec("UPDATE anchors SET sig=? WHERE sig IS NULL AND action_id<=?", (sig, last["action_id"]))
        log.info("anchored %d log entries on Solana (up to #%d): %s", len(todo), last["action_id"], sig)
        return sig

    def reset(self):
        self.store._exec("DELETE FROM anchors")

    def by_action(self):
        return {r["action_id"]: r["sig"] for r in self.store._all("SELECT action_id, sig FROM anchors")}

    def checkpoints(self):
        return self.store._all("SELECT sig, MAX(action_id) AS last_id, COUNT(*) AS entries FROM anchors "
                               "WHERE sig IS NOT NULL GROUP BY sig ORDER BY last_id")

    def summary(self):
        cps = self.checkpoints()
        return {"enabled": enabled(), "cluster": cluster(), "entries": len(self.by_action()),
                "pending": len(self.pending()), "checkpoints": len(cps),
                "latest": explorer(cps[-1]["sig"]) if cps else None, "error": self.last_error}

    def verify(self, onchain=True, max_checkpoints=8):
        """Recompute the chain from the log and compare it with the stored fingerprints and with Solana."""
        stored = {r["action_id"]: r for r in self.store._all("SELECT * FROM anchors")}
        rows = self._rows()
        recomputed, prev = {}, GENESIS
        for row in rows:
            prev = recomputed[row["id"]] = row_hash(prev, row)
        missing = sorted(set(stored) - set(recomputed))
        if missing:
            return {"ok": False, "problem": f"Log entry #{missing[0]} was deleted.", "entry": missing[0]}
        for row in rows:
            s = stored.get(row["id"])
            if s and s["hash"] != recomputed[row["id"]]:
                return {"ok": False, "problem": f"Log entry #{row['id']} was changed after it was recorded.",
                        "entry": row["id"]}
        cps = self.checkpoints()
        checked = 0
        if onchain:
            for cp in cps[-max_checkpoints:]:
                memo = read_memo(cp["sig"])
                if memo is None:
                    continue                      # not confirmed yet
                if memo != memo_text(cp["last_id"], recomputed.get(cp["last_id"], "")):
                    return {"ok": False, "entry": cp["last_id"], "tx": explorer(cp["sig"]),
                            "problem": f"The log up to entry #{cp['last_id']} doesn't match what Solana recorded."}
                checked += 1
        return {"ok": True, "entries": len(rows), "anchored": sum(1 for s in stored.values() if s["sig"]),
                "checkpoints": len(cps), "checked_on_solana": checked, "cluster": cluster(),
                "latest": explorer(cps[-1]["sig"]) if cps else None}

    async def run(self, every=4.0):
        """Background loop: keep the chain up to date and anchor new entries."""
        while True:
            await asyncio.sleep(30.0 if self.last_error else every)   # back off while Solana is refusing
            try:
                await asyncio.to_thread(self.checkpoint)
                self.last_error = None
            except Exception as e:                # never let the notary stop Warden from working
                msg = str(e)
                if "pay transaction fees" in msg or "insufficient" in msg.lower():
                    msg = "The Solana wallet has no test SOL. Fund it at https://faucet.solana.com (see `make solana`)."
                if msg != self.last_error:
                    log.warning("Solana anchoring failed (will retry): %s", msg)
                self.last_error = msg


def main():
    """make solana: create the devnet wallet and ask the faucet for test SOL."""
    kp = create_wallet()
    print(f"Wallet: {kp.pubkey()}  ({cluster()})")
    bal = balance(kp.pubkey())
    if bal < 0.05 and cluster() != "mainnet-beta":
        try:
            _rpc("requestAirdrop", [str(kp.pubkey()), 1_000_000_000])
            print("Asked the faucet for 1 test SOL (takes a few seconds to arrive).")
        except Exception as e:
            print(f"The faucet refused ({e}).\nGet free test SOL at https://faucet.solana.com for the wallet above.")
    print(f"Balance: {bal} SOL. Each checkpoint costs 0.000005 SOL.")


if __name__ == "__main__":
    main()
