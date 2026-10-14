"""Compatibility bridge for llm_research module.

The legacy app.py expects llm_research in the trading-lab root.
This imports from the API version to maintain backward compatibility.
"""
import sys
from pathlib import Path

# Add API directory to path for the real llm_research
_api_dir = Path(__file__).resolve().parent / "api"
if str(_api_dir) not in sys.path:
    sys.path.insert(0, str(_api_dir))

# Re-export the API version
from llm_research import LLMResearchLayer, ModelError, is_free_model, PROVIDER_SPECS

# Also re-export the legacy ResearchLayer for compatibility
from llm_research_legacy import ResearchLayer

__all__ = ["LLMResearchLayer", "ModelError", "is_free_model", "PROVIDER_SPECS", "ResearchLayer"]