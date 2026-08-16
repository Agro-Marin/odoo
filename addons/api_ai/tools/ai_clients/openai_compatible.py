import logging

from ..vendor_catalog import (
    TRANSCRIBE_TIMEOUT,
    audio_mimetype,
    build_whisper_form,
    read_openai_content,
    read_whisper_transcript,
)
from .base import BaseAIClient
from odoo.addons.api_transport.tools.exceptions import CommError

_logger = logging.getLogger(__name__)


class OpenAICompatibleClient(BaseAIClient):
    MAX_TEMPERATURE = 2.0
    MIN_TEMPERATURE = 0.0

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

    def chat_completion(
        self,
        messages,
        model=None,
        temperature=1.0,
        max_tokens=4096,
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
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **kwargs,
            }

            response = self._client.post("/chat/completions", json=payload)
            return self._validate_response(response)

        except ValueError, CommError:
            raise
        except Exception as e:
            raise CommError(
                f"{type(self).__name__} chat completion failed: {e!s}",
            ) from e

    def simple_completion(self, prompt, model=None, **kwargs):
        model = self._resolve_model(model)
        try:
            messages = [{"role": "user", "content": prompt}]
            result = self.chat_completion(messages=messages, model=model, **kwargs)

            content, problem = read_openai_content(result)
            if problem:
                _logger.error(
                    "%s returned no usable content: %s. Response: %s",
                    type(self).__name__,
                    problem,
                    result,
                )
                raise CommError(
                    f"{type(self).__name__} returned no usable content: "
                    f"{problem}. This may indicate an API change, a truncated "
                    f"answer, or an invalid request.",
                )
            return content

        except CommError:
            raise
        except Exception as e:
            raise CommError(
                f"{type(self).__name__} simple completion failed: {e!s}",
            ) from e

    def vision_completion(
        self,
        prompt,
        image_data,
        media_type="image/jpeg",
        model=None,
        **kwargs,
    ):
        spec = self._catalog_spec()
        if not spec or not spec.get("vision"):
            raise CommError(
                f"{type(self).__name__} reads no images: the catalog describes "
                f"no vision capability for {self.ENDPOINT_CODE!r}",
            )
        if not image_data:
            raise CommError(f"{type(self).__name__} was given no image to send")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{image_data}"},
                    },
                ],
            }
        ]
        result = self.chat_completion(
            messages=messages,
            model=model or spec.get("vision_model"),
            **kwargs,
        )

        content, problem = read_openai_content(result)
        if problem:
            raise CommError(
                f"{type(self).__name__} returned no usable answer for the "
                f"image: {problem}",
            )
        return content

    def transcribe(self, audio_bytes, filename, language="es", prompt=None):
        spec = self._catalog_spec()
        if not spec or not spec.get("audio"):
            raise CommError(
                f"{type(self).__name__} has no transcription endpoint: the "
                f"catalog describes no audio wire for {self.ENDPOINT_CODE!r}",
            )
        if spec["audio"] != "whisper":
            raise CommError(
                f"{self.ENDPOINT_CODE!r} transcribes over the "
                f"{spec['audio']!r} wire, which this client does not speak",
            )
        if spec.get("audio_service") != self.ENDPOINT_CODE:
            raise CommError(
                f"{self.ENDPOINT_CODE!r} serves audio on "
                f"{spec['audio_service']!r}; build a client for that endpoint",
            )

        if not audio_bytes:
            raise CommError(f"{type(self).__name__} was given no audio to send")

        try:
            response = self._client.post(
                spec["audio_path"],
                files={"file": (filename, audio_bytes, audio_mimetype(filename))},
                data=build_whisper_form(
                    spec["audio_model"], language=language, prompt=prompt
                ),
                timeout=spec.get("audio_timeout") or TRANSCRIBE_TIMEOUT,
            )
        except CommError:
            raise
        except Exception as e:
            raise CommError(
                f"{type(self).__name__} transcription failed: {e!s}",
            ) from e

        text, problem = read_whisper_transcript(
            response.get("body") if isinstance(response, dict) else response
        )
        if problem:
            raise CommError(
                f"{type(self).__name__} returned no usable transcript: {problem}",
            )
        return text

    def get_usage(self, response):
        usage = response.get("usage") or {}
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "model": response.get("model", "unknown"),
        }
