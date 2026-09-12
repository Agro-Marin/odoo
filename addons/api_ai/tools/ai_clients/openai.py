from .openai_compatible import OpenAICompatibleClient


class OpenAIClient(OpenAICompatibleClient):
    ENDPOINT_CODE = "openai"

    MAX_TOKENS_LIMIT = 16384


def get_openai_client(env, company_id=None):
    return OpenAIClient(env, company_id)
