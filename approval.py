"""Human-approval gate. Tokens are only minted here, after an explicit human decision,
and are bound to a hash of the exact arguments they approve (single use)."""
import hashlib
import json
import secrets
from pathlib import Path

LEDGER = Path(__file__).parent / "out" / "approvals.json"


def _digest(action: str, args: dict) -> str:
    return hashlib.sha256(json.dumps([action, args], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _load() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}


def issue_token(action: str, args: dict) -> str:
    """Call ONLY after the human has approved this action."""
    LEDGER.parent.mkdir(exist_ok=True)
    ledger = _load()
    token = secrets.token_hex(16)
    ledger[token] = dict(action=action, digest=_digest(action, args), used=False)
    LEDGER.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    return token


def consume_token(action: str, args: dict, token: str) -> None:
    ledger = _load()
    rec = ledger.get(token)
    if not rec or rec["used"] or rec["action"] != action or rec["digest"] != _digest(action, args):
        raise PermissionError(f"{action}: missing, used, or mismatched approval token. Human approval required.")
    rec["used"] = True
    LEDGER.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
