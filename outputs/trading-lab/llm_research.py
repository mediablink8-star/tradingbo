"""Compatibility bridge for llm_research module.

The legacy app.py expects llm_research in the trading-lab root.
The real implementations live in:
  - llm_research_legacy.py  (legacy ResearchLayer / ModelError / verify_connection)
  - key_store.py             (PROVIDER_SPECS / is_free_model)
  - api/llm_research.py      (API-side LLMResearchLayer)

This file IS llm_research, so importing from llm_research by name would be a
circular import. The API version is loaded via importlib under a synthetic
module name to avoid that collision.
"""
import importlib.util
import sys
from pathlib import Path

# --- Legacy symbols: the app imports these from llm_research ------------
from llm_research_legacy import (
    ResearchLayer,
    ModelError,
    verify_connection,
)

# --- Symbols that live in key_store -----------------------------------
from key_store import PROVIDER_SPECS, is_free_model

# --- API-side LLMResearchLayer (loaded by file path to avoid collision) -
LLMResearchLayer = None

_api_dir = Path(__file__).resolve().parent / "api"
if str(_api_dir) not in sys.path:
    sys.path.insert(0, str(_api_dir))

_api_llm_module = None
try:
    _spec_obj = importlib.util.spec_from_file_location(
        "_api_llm_research_bridge",
        str(_api_dir / "llm_research.py"),
    )
    if _spec_obj is not None and _spec_obj.loader is not None:
        _api_llm_module = importlib.util.module_from_spec(_spec_obj)
        sys.modules["_api_llm_research_bridge"] = _api_llm_module
        _spec_obj.loader.exec_module(_api_llm_module)
        LLMResearchLayer = getattr(_api_llm_module, "LLMResearchLayer", None)
except Exception:
    # API version is optional; the core app only needs the legacy symbols.
    pass

__all__ = [
    "LLMResearchLayer",
    "ModelError",
    "is_free_model",
    "PROVIDER_SPECS",
    "ResearchLayer",
    "verify_connection",
]