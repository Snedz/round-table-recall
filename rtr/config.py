"""Credential and settings loading.

Values come from environment variables first. If a variable is missing, a
file of the same lowercase name is read from ``RTR_SECRETS_DIR`` (default
``/workspace/secrets/tatum-walrus``). Values are never logged or printed;
use :func:`redact` when something must be shown.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SECRETS_DIR = "/workspace/secrets/tatum-walrus"

# env var -> secret file name (in RTR_SECRETS_DIR) or a fallback file path
_FILE_FALLBACKS = {
    "MEMWAL_ACCOUNT_ID": "memwal_account_id",
    "MEMWAL_PRIVATE_KEY": "memwal_delegate_private_key",
    "MEMWAL_AGENT_ID": "memwal_agent_id",
    "SUI_ADDRESS": "sui_address",
    "TATUM_ID": "tatum_id",
    "TATUM_API_KEY_MAINNET": "tatum_api_key_mainnet",
    "TATUM_API_KEY_TESTNET": "tatum_api_key_testnet",
    "NVIDIA_API_KEY": "~/.config/p67/nvidia.env",
    "OPENROUTER_API_KEY": "~/.p67_or.key",
    "OPENCODE_API_KEY": "opencode_api_key",
}


def _read_file_value(path: Path, var: str) -> str | None:
    try:
        raw = path.read_text().strip()
    except OSError:
        return None
    if not raw:
        return None
    # Accept either a bare value or KEY=VALUE lines.
    for line in raw.splitlines():
        line = line.strip()
        line = line.removeprefix("export ")
        if line.startswith(f"{var}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    if "=" in raw.splitlines()[0]:
        return None
    return raw.splitlines()[0].strip()


def get(var: str) -> str | None:
    """Return a credential or setting, or ``None`` when it is not available."""
    if var.startswith("TATUM_API_KEY") and os.environ.get("RTR_TATUM_KEYLESS") == "1":
        return None  # force Tatum's anonymous plan: what a judge without a Tatum account sees
    val = os.environ.get(var)
    if val:
        return val.strip()
    hint = _FILE_FALLBACKS.get(var)
    if not hint:
        return None
    if hint.startswith(("~", "/")):
        path = Path(hint).expanduser()
    else:
        path = Path(os.environ.get("RTR_SECRETS_DIR", DEFAULT_SECRETS_DIR)) / hint
    return _read_file_value(path, var)


def redact(value: str | None) -> str:
    if not value:
        return "<missing>"
    return f"<set, {len(value)} chars>"


def network() -> str:
    """``mainnet`` or ``testnet`` (default mainnet once credentials exist)."""
    return os.environ.get("RTR_NETWORK", "mainnet").lower()


def state_dir() -> Path:
    p = Path(os.environ.get("RTR_STATE_DIR", Path.cwd() / ".rtr"))
    p.mkdir(parents=True, exist_ok=True)
    return p
