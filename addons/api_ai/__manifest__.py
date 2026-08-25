{
    "name": "API AI",
    "version": "19.0.1.15.0",
    "category": "Technical",
    "sequence": 10,
    "summary": "AI provider registry, orchestration and vendor clients",
    "description": """
API AI
======

AI layer on the outbound API transport.

Models
------
* ``ai.provider`` -- delegates to ``api.endpoint.outbound``; holds what the API
  key decides: reliability, free tier, fallback chain, and ``has_vision`` /
  ``has_audio`` rolled up from its models
* ``ai.model`` -- holds what the model name decides: cost per token, context
  window, output cap, vision, function calling, accuracy and speed. A provider
  names one of its own as ``default_model_id``, and that is the model
  ``AIOrchestrator`` ranks on and ``_resolve_model`` runs. ADR-0039.
* ``ai.use.case.tag`` -- provider classification: vision, reasoning, speed,
  budget, long context, OCR, embeddings, audio

Vendor catalog
--------------
``tools/vendor_catalog.py`` holds ``PROVIDERS``: per-vendor endpoint paths,
model defaults, vision and audio capability, and the timeouts and token floors
measured against live keys. Callers that build their own request bodies read it
instead of restating it -- ``telegram_bot`` is the one that does, because a
bot's key belongs to the bot rather than the company and so cannot go through
``credential.credential``. ``build_openai_content`` and
``build_anthropic_content`` shape the two chat wires; ``strip_json_fence``, in
``tools/json_payload.py``, is the fence half of ``parse_json_response`` for
callers that must not let it raise.

Orchestration
-------------
* ``AIOrchestrator.select_model`` picks an ``ai.model`` by cost, accuracy, speed
  or balanced score, filtered by the model's own capability and by credential
  availability for the current company. ``select_provider`` still answers the
  vendor-level question a credential and a breaker are scoped to.
* ``execute_with_fallback`` walks ``ai.model.fallback_model_ids``. A hop may stay
  on one vendor -- a smaller model on a key already held -- or cross to another.
  Nothing seeds a chain: acceptable degradation is a deployment's to state.
  ADR-0040.

Clients
-------
Three ways to reach a vendor. The first two are on the generic HTTP transport
and so inherit session pooling, retry, rate limiting, response caching, secret
redaction and the event log.

* ``tools/ai_clients/`` -- a class per vendor: Claude, DeepSeek, OpenAI, Gemini
  and Deepgram. Raising, credential resolved from the company, rich where a
  vendor is rich (prompt caching, tool-call structured output, model tables).
  What ``AIOrchestrator`` drives.
* ``tools/catalog_client.py`` -- ``CatalogAIClient``, one class driving every
  catalog vendor off ``PROVIDERS``. Fail-soft, key passed in per call, and the
  only way to reach the ``gemini_openai`` endpoint, which the catalog's
  ``gemini`` entry uses for chat and which no class targets -- ``GeminiClient``
  is on ``gemini``, the native wire. ``groq`` and ``moonshot`` DO have classes,
  in ``tools/ai_clients/openai_wire_vendors.py``, registered like the rest:
  ``tests/test_registry_coherence.py`` requires every catalog vendor to be in
  ``AI_CLIENT_REGISTRY`` so that ``_get_ai_client`` can answer for whichever one
  the orchestrator selects. Neither is re-exported from ``tools/__init__.py``.
  It arrived from ``telegram_bot`` in 19.0.1.7.0, where being a second
  implementation of the same two chat wires had let the two drift.

The third is not HTTP at all and so inherits none of that.

* ``tools/claude_sdk.py`` -- ``ClaudeSDKClient`` drives ``claude_agent_sdk``,
  which spawns the Claude Code CLI as a Node subprocess and lets it read and
  write files under a work-dir root the caller names. ``get_claude_api_token``
  is beside it because a subprocess needs the key as a string in its
  environment, which ``get_api_client`` cannot hand back. The SDK import is
  soft: absent ``claude-agent-sdk``, the module still imports and the client
  raises on construction, so nothing here is an ``external_dependencies`` entry
  for the modules that merely need the HTTP path. It is deliberately **not**
  re-exported from ``tools/__init__.py``: importing ``claude_agent_sdk`` costs
  343ms and 137 modules, and ``api_ai_agent``, ``telegram_bot`` and
  ``document_extract_ai`` all import that package without ever driving a
  subprocess. Import the submodule. It arrived from ``agromarin/ai_claude`` in
  19.0.1.15.0.

``read_openai_content`` and ``read_anthropic_content`` in ``vendor_catalog``
are the single reader per wire that both stacks use.

Depends on ``api_transport`` alone.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "api_transport",
    ],
    "data": [
        "security/api_ai_security.xml",
        "security/ir.model.access.csv",
        "data/ai_services_data.xml",
        "data/ai_use_case_tags_data.xml",
        "data/ai_providers_data.xml",
        "data/ai_models_data.xml",
        "views/ai_provider_views.xml",
        "views/ai_model_views.xml",
        "views/ai_use_case_tag_views.xml",
        "views/ai_menu.xml",
    ],
    "pre_init_hook": "pre_init_hook",
}
