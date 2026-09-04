from __future__ import annotations

import logging
from typing import Any

from odoo.addons.api_ai.tools.ai_orchestrator import get_ai_orchestrator

_logger = logging.getLogger(__name__)

TRANSCRIPTION_KIND = "audio"
SYNTHESIS_KIND = "speech"


def pick_model(env: Any, kind: str, optimize_for: str = "balanced") -> Any:
    model = get_ai_orchestrator(env).select_model(kind=kind, optimize_for=optimize_for)
    if not model:
        _logger.info(
            "No %s model is configured with a usable credential; speech stays "
            "unavailable rather than failing at a vendor call",
            kind,
        )
    return model


def run(env: Any, model: Any, request_func: Any, log_metadata: dict | None = None):
    return get_ai_orchestrator(env).execute_with_fallback(
        model, request_func, log_metadata=log_metadata
    )
