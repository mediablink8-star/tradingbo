"""Jupiter / Solana swap placeholder — live only when key + ARM present."""
from __future__ import annotations

from typing import Any

from config import Settings


class JupiterClient:
    def __init__(self, settings: Settings):
        self.rpc = settings.solana_rpc_url
        self.has_key = bool(settings.solana_private_key)

    def status(self) -> dict[str, Any]:
        return {
            "broker": "jupiter_solana",
            "rpc": self.rpc,
            "wallet_configured": self.has_key,
            "note": "Live swaps require SOLANA_PRIVATE_KEY + risk ARM. Paper path uses existing meme trader.",
        }
