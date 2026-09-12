from .openai_compatible import OpenAICompatibleClient


class OpenAIClient(OpenAICompatibleClient):
    ENDPOINT_CODE = "openai"

    VALID_MODELS = [
        "gpt-5.1",
        "gpt-5.1-instant",
        "gpt-5.1-thinking",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
        "o3",
        "o4-mini",
        "o1",
        "o1-mini",
        "o1-preview",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
    ]

    MAX_TOKENS_LIMIT = 16384


def get_openai_client(env, company_id=None):
    return OpenAIClient(env, company_id)
