import logging

from ..vendor_catalog import read_anthropic_content
from .base import BaseAIClient
from odoo.addons.api_transport.tools.exceptions import CommError

_logger = logging.getLogger(__name__)


CLAUDE_MODELS = (
    ("claude-opus-5", "Claude Opus 5"),
    ("claude-sonnet-5", "Claude Sonnet 5"),
    ("claude-opus-4-8", "Claude Opus 4.8"),
    ("claude-opus-4-7", "Claude Opus 4.7"),
    ("claude-opus-4-6", "Claude Opus 4.6"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("claude-sonnet-4-5", "Claude Sonnet 4.5"),
    ("claude-haiku-4-5", "Claude Haiku 4.5"),
)

CLAUDE_MODEL_ALIASES = (
    ("claude-sonnet-4-5-20250929", "Claude Sonnet 4.5"),
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
)


class ClaudeClient(BaseAIClient):
    ENDPOINT_CODE = "claude"

    VALID_MODELS = [model_id for model_id, _label in CLAUDE_MODELS]

    NO_SAMPLING_PARAMS = frozenset(
        {
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-fable-5",
            "claude-opus-4-8",
            "claude-opus-4-7",
        }
    )

    MAX_TEMPERATURE = 1.0
    MIN_TEMPERATURE = 0.0
    MAX_TOKENS_LIMIT = 8192

    def _validate_response(self, response_data):
        if not isinstance(response_data, dict):
            raise CommError(
                f"Invalid response type: expected dict but got {type(response_data).__name__}",
            )

        body = response_data.get("body")
        if body is None:
            _logger.error("Response missing 'body' key: %s", response_data)
            raise CommError(
                f"Invalid response structure: missing 'body' field. Got keys: {list(response_data.keys())}",
            )

        if not isinstance(body, dict):
            raise CommError(
                f"Invalid API response body: expected dict but got {type(body).__name__}",
            )

        return body

    def _extract_text_from_response(self, result):
        text, problem = read_anthropic_content(result)
        if problem:
            _logger.error(
                "Claude API returned no usable text content: %s. Response: %s",
                problem,
                result,
            )
            raise CommError(
                f"Claude API returned no usable text content: {problem}. This "
                f"may indicate an API change, a truncated answer, or an "
                f"invalid request.",
            )
        return text

    def create_message(
        self,
        messages,
        model=None,
        max_tokens=4096,
        temperature=1.0,
        system=None,
        thinking=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        try:
            self._validate_params(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
                **kwargs,
            }

            if model not in self.NO_SAMPLING_PARAMS:
                payload["temperature"] = temperature

            if system:
                payload["system"] = system

            if thinking:
                payload["thinking"] = thinking

            _logger.debug(
                "Claude create_message request: model=%s, messages=%s",
                model,
                len(messages),
            )
            response = self._client.post("/messages", json=payload)
            return self._validate_response(response)

        except ValueError as e:
            _logger.error("Invalid parameters for Claude create_message: %s", e)
            raise
        except CommError as e:
            _logger.error("Claude API error in create_message: %s", e)
            raise
        except Exception as e:
            _logger.exception("Unexpected error in Claude create_message")
            raise CommError(f"Claude create_message failed: {e!s}") from e

    def simple_completion(self, prompt, model=None, **kwargs):
        model = self._resolve_model(model)
        try:
            messages = [{"role": "user", "content": prompt}]
            result = self.create_message(messages=messages, model=model, **kwargs)
            return self._extract_text_from_response(result)

        except CommError:
            raise
        except Exception as e:
            _logger.exception("Unexpected error in Claude simple_completion")
            raise CommError(f"Claude simple completion failed: {e!s}") from e

    def streaming_completion(self, messages, model=None, **kwargs):
        model = self._resolve_model(model)
        try:
            self._validate_params(model=model, temperature=kwargs.get("temperature"))

            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                **kwargs,
            }

            _logger.debug(
                "Claude streaming completion request: model=%s, messages=%s",
                model,
                len(messages),
            )
            response = self._client.post(
                "/messages", json=payload, stream=True, raw=True
            )

            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    decoded = line.decode("utf-8")
                except UnicodeDecodeError as e:
                    _logger.warning(
                        "Failed to decode Claude streaming chunk: %s. Skipping.",
                        e,
                    )
                    continue
                yield decoded

        except CommError:
            raise
        except Exception as e:
            _logger.exception("Unexpected error in Claude streaming_completion")
            raise CommError(f"Claude streaming completion failed: {e!s}") from e

    def vision_completion(
        self,
        prompt,
        image_data,
        media_type="image/jpeg",
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                    ],
                },
            ]

            result = self.create_message(messages=messages, model=model, **kwargs)
            return self._extract_text_from_response(result)

        except CommError:
            raise
        except Exception as e:
            _logger.exception("Unexpected error in Claude vision_completion")
            raise CommError(f"Claude vision completion failed: {e!s}") from e

    def get_usage(self, response):
        usage_data = response.get("usage", {})
        model = response.get("model", "claude-sonnet-4-5")

        input_tokens = usage_data.get("input_tokens", 0)
        output_tokens = usage_data.get("output_tokens", 0)
        cache_creation_tokens = usage_data.get("cache_creation_input_tokens", 0)
        cache_read_tokens = usage_data.get("cache_read_input_tokens", 0)

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cache_creation_input_tokens": cache_creation_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "model": model,
        }

    def structured_output(
        self,
        prompt,
        schema,
        tool_name="extract_data",
        tool_description="Extract structured data",
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        tools = [
            {
                "name": tool_name,
                "description": tool_description,
                "input_schema": schema,
            },
        ]

        tool_choice = {"type": "tool", "name": tool_name}

        response = self.create_message(
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice=tool_choice,
            model=model,
            **kwargs,
        )

        for block in response.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == tool_name:
                return block.get("input", {})

        return {}

    def vision_structured_output(
        self,
        prompt,
        image_data,
        schema,
        media_type="image/jpeg",
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        tools = [
            {
                "name": "extract_from_image",
                "description": "Extract structured data from image",
                "input_schema": schema,
            },
        ]

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                ],
            },
        ]

        tool_choice = {"type": "tool", "name": "extract_from_image"}

        response = self.create_message(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            model=model,
            **kwargs,
        )

        for block in response.get("content", []):
            if block.get("type") == "tool_use":
                return block.get("input", {})

        return {}

    def create_cacheable_content(self, text, cache=True, ttl=None):
        content = {"type": "text", "text": text}

        if cache:
            cache_control = {"type": "ephemeral"}
            if ttl:
                cache_control["ttl"] = ttl
            content["cache_control"] = cache_control

        return content

    def create_cached_system_prompt(self, guidelines, cache_guidelines=True):
        return [self.create_cacheable_content(guidelines, cache=cache_guidelines)]

    def tool_conversation(
        self,
        user_message,
        tools,
        tool_executor,
        max_turns=5,
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        messages = [{"role": "user", "content": user_message}]

        for _turn in range(max_turns):
            response = self.create_message(
                messages=messages,
                tools=tools,
                model=model,
                **kwargs,
            )

            stop_reason = response.get("stop_reason")

            if stop_reason in {"end_turn", "stop_sequence"}:
                return response

            if stop_reason == "tool_use":
                assistant_content = response.get("content", [])
                tool_results = []

                for block in assistant_content:
                    if block.get("type") == "tool_use":
                        tool_name = block.get("name")
                        tool_input = block.get("input", {})
                        tool_use_id = block.get("id")

                        try:
                            result = tool_executor(tool_name, tool_input)
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_use_id,
                                    "content": str(result),
                                },
                            )
                        except Exception as e:
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_use_id,
                                    "content": f"Error: {e!s}",
                                    "is_error": True,
                                },
                            )

                messages.append({"role": "assistant", "content": assistant_content})

                messages.append({"role": "user", "content": tool_results})

                continue

            return response

        return {
            "error": "Max tool use turns reached",
            "messages": messages,
            "last_response": response,
        }

    def enable_extended_context(self):
        try:
            if hasattr(self._client, "session") and self._client.session:
                self._client.session.headers["anthropic-beta"] = "context-1m-2025-08-07"
                _logger.debug("Extended context (1M tokens) enabled for Claude client")
            else:
                _logger.warning(
                    "Could not enable extended context: API client session not available",
                )
        except Exception as e:
            _logger.error("Failed to enable extended context: %s", e)

        return self

    def pdf_completion(
        self,
        prompt,
        pdf_data,
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_data,
                            },
                        },
                    ],
                },
            ]

            result = self.create_message(messages=messages, model=model, **kwargs)
            return self._extract_text_from_response(result)

        except CommError:
            raise
        except Exception as e:
            _logger.exception("Unexpected error in Claude pdf_completion")
            raise CommError(f"Claude PDF completion failed: {e!s}") from e

    def pdf_structured_output(
        self,
        prompt,
        pdf_data,
        schema,
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        tools = [
            {
                "name": "extract_from_pdf",
                "description": "Extract structured data from PDF document",
                "input_schema": schema,
            },
        ]

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        },
                    },
                ],
            },
        ]

        tool_choice = {"type": "tool", "name": "extract_from_pdf"}

        response = self.create_message(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            model=model,
            **kwargs,
        )

        for block in response.get("content", []):
            if block.get("type") == "tool_use":
                return block.get("input", {})

        return {}

    def pdf_with_caching(
        self,
        prompt,
        pdf_data,
        cache_pdf=True,
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        try:
            doc_block = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_data,
                },
            }

            if cache_pdf:
                doc_block["cache_control"] = {"type": "ephemeral"}

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        doc_block,
                    ],
                },
            ]

            result = self.create_message(messages=messages, model=model, **kwargs)
            return self._extract_text_from_response(result)

        except CommError:
            raise
        except Exception as e:
            _logger.exception("Unexpected error in Claude pdf_with_caching")
            raise CommError(f"Claude PDF with caching failed: {e!s}") from e


def get_claude_client(env, company_id=None):
    return ClaudeClient(env, company_id)
