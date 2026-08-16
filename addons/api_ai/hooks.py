import logging

_logger = logging.getLogger(__name__)

_OLD_MODULE = "api_gateway"
_NEW_MODULE = "api_ai"

_MOVED_RECORDS = {
    "api.endpoint.outbound": [
        "service_anthropic",
        "service_deepseek",
        "service_openai",
        "service_google",
        "service_deepgram",
    ],
    "ai.provider": [
        "ai_provider_google",
        "ai_provider_anthropic",
        "ai_provider_openai",
        "ai_provider_deepseek",
    ],
    "ai.use.case.tag": [
        "tag_vision",
        "tag_reasoning",
        "tag_speed",
        "tag_budget",
        "tag_accuracy",
        "tag_long_context",
        "tag_ocr",
        "tag_embeddings",
        "tag_chat",
        "tag_content_generation",
    ],
    "ir.ui.view": [
        "view_ai_provider_search",
        "view_ai_provider_list",
        "view_ai_provider_kanban",
        "view_ai_provider_form",
        "view_ai_use_case_tag_list",
        "view_ai_use_case_tag_form",
        "view_ai_use_case_tag_search",
    ],
    "ir.actions.act_window": [
        "action_ai_provider",
        "action_ai_use_case_tag",
    ],
    "ir.model.access": [
        "access_ai_provider_user",
        "access_ai_provider_admin",
        "access_ai_provider_system",
        "access_ai_use_case_tag_user",
        "access_ai_use_case_tag_admin",
        "access_ai_use_case_tag_system",
    ],
}


def _retag_moved_records(env):
    retagged = 0
    for model, names in _MOVED_RECORDS.items():
        env.cr.execute(
            """
            UPDATE ir_model_data d
               SET module = %(new)s
             WHERE d.module = %(old)s
               AND d.model = %(model)s
               AND d.name = ANY(%(names)s)
               AND NOT EXISTS (
                     SELECT 1
                       FROM ir_model_data e
                      WHERE e.module = %(new)s
                        AND e.name = d.name
                        AND e.model = d.model
                   )
            """,
            {
                "new": _NEW_MODULE,
                "old": _OLD_MODULE,
                "model": model,
                "names": names,
            },
        )
        if env.cr.rowcount:
            retagged += env.cr.rowcount
            _logger.info(
                "api_ai: re-tagged %s %s record(s) from %s",
                env.cr.rowcount,
                model,
                _OLD_MODULE,
            )
    if retagged:
        _logger.info(
            "api_ai: took ownership of %s record(s) from %s, preserving their ids "
            "so the data load updates in place and views keep their identity",
            retagged,
            _OLD_MODULE,
        )


def pre_init_hook(env):
    _retag_moved_records(env)
