import json
import logging

from .openai_compatible import OpenAICompatibleClient

_logger = logging.getLogger(__name__)


class DeepSeekClient(OpenAICompatibleClient):
    ENDPOINT_CODE = "deepseek"

    VALID_MODELS = ["deepseek-chat", "deepseek-reasoner"]

    MAX_TEMPERATURE = 2.0
    MIN_TEMPERATURE = 0.0
    MAX_TOKENS_LIMIT = 8192

    def _iter_stream_lines(self, response):
        for line in response.iter_lines():
            if line:
                yield line.decode("utf-8")

    def code_completion(self, prompt, model=None, **kwargs):
        return self.simple_completion(prompt, model=model, **kwargs)

    def streaming_completion(self, messages, model=None, **kwargs):
        model = self._resolve_model(model)
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs,
        }

        response = self._client.post(
            "/chat/completions", json=payload, stream=True, raw=True
        )

        yield from self._iter_stream_lines(response)

    def structured_output(
        self,
        prompt,
        schema,
        tool_name="extract_data",
        tool_description="Extract structured data from the input",
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": schema,
                },
            },
        ]

        tool_choice = {"type": "function", "function": {"name": tool_name}}

        messages = [{"role": "user", "content": prompt}]

        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            **kwargs,
        }

        try:
            response = self._client.post("/chat/completions", json=payload)
            result = self._validate_response(response)

            if result.get("choices") and len(result["choices"]) > 0:
                message = result["choices"][0].get("message", {})
                tool_calls = message.get("tool_calls", [])

                if tool_calls and len(tool_calls) > 0:
                    arguments_str = tool_calls[0]["function"]["arguments"]
                    try:
                        return json.loads(arguments_str)
                    except json.JSONDecodeError as e:
                        _logger.error("Failed to parse tool call arguments: %s", e)
                        return {}

            _logger.error("No tool call in response: %s", result)
            return {}

        except Exception:
            _logger.exception("Structured output error")
            raise

    def reasoning_completion(
        self,
        prompt,
        max_tokens=5000,
        model="deepseek-reasoner",
        **kwargs,
    ):
        messages = [{"role": "user", "content": prompt}]

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            **kwargs,
        }

        try:
            response = self._client.post("/chat/completions", json=payload)
            result = self._validate_response(response)

            if result.get("choices") and len(result["choices"]) > 0:
                message = result["choices"][0].get("message", {})

                return {
                    "content": message.get("content", ""),
                    "usage": self.get_usage(result),
                    "model": result.get("model", model),
                }

            return {
                "content": "",
                "usage": {},
                "model": model,
            }

        except Exception:
            _logger.exception("Reasoning completion error")
            raise

    def tool_conversation(
        self,
        prompt,
        tools,
        tool_executor,
        max_turns=10,
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        messages = [{"role": "user", "content": prompt}]
        conversation_history = []

        for turn in range(max_turns):
            payload = {
                "model": model,
                "messages": messages,
                "tools": tools,
                **kwargs,
            }

            try:
                response = self._client.post("/chat/completions", json=payload)
                result = self._validate_response(response)

                if not result.get("choices"):
                    break

                message = result["choices"][0].get("message", {})
                messages.append(message)
                conversation_history.append(message)

                tool_calls = message.get("tool_calls", [])

                if not tool_calls:
                    return {
                        "content": message.get("content", ""),
                        "conversation_history": conversation_history,
                        "turns": turn + 1,
                        "usage": self.get_usage(result),
                    }

                for tool_call in tool_calls:
                    tool_name = tool_call.get("function", {}).get("name", "")
                    tool_args_str = tool_call.get("function", {}).get("arguments", "{}")

                    try:
                        tool_args = json.loads(tool_args_str)
                    except json.JSONDecodeError as e:
                        _logger.error("Failed to parse tool arguments: %s", e)
                        tool_args = {}

                    try:
                        tool_result = tool_executor(tool_name, tool_args)

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.get("id", ""),
                                "content": json.dumps(tool_result),
                            },
                        )

                    except Exception as e:
                        _logger.exception("Tool execution error")
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.get("id", ""),
                                "content": json.dumps({"error": str(e)}),
                            },
                        )

            except Exception:
                _logger.exception("Tool conversation error")
                raise

        return {
            "content": "Maximum conversation turns reached",
            "conversation_history": conversation_history,
            "turns": max_turns,
            "usage": {},
        }

    def streaming_json_completion(self, prompt, model=None, **kwargs):
        model = self._resolve_model(model)
        if "json" not in prompt.lower():
            prompt = f"{prompt}\n\nProvide the response as JSON."

        messages = [{"role": "user", "content": prompt}]

        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "stream": True,
            **kwargs,
        }

        response = self._client.post(
            "/chat/completions", json=payload, stream=True, raw=True
        )

        yield from self._iter_stream_lines(response)

    def math_completion(self, problem, max_tokens=5000, **kwargs):
        enhanced_prompt = f"""Solve the following mathematical problem step by step:

{problem}

Show your work clearly and provide the final answer."""

        return self.reasoning_completion(
            enhanced_prompt,
            max_tokens=max_tokens,
            **kwargs,
        )

    def code_review(self, code, language="python", **kwargs):
        schema = {
            "type": "object",
            "properties": {
                "overall_quality": {
                    "type": "string",
                    "enum": ["excellent", "good", "fair", "poor"],
                },
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "major", "minor"],
                            },
                            "description": {"type": "string"},
                            "line_number": {"type": "integer"},
                        },
                    },
                },
                "suggestions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "strengths": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["overall_quality", "issues", "suggestions"],
        }

        prompt = f"""Review this {language} code and provide structured feedback:

```{language}
{code}
```

Analyze:
1. Code quality and style
2. Potential bugs or issues
3. Performance concerns
4. Security vulnerabilities
5. Best practices adherence

Provide structured feedback matching the schema."""

        return self.structured_output(
            prompt=prompt,
            schema=schema,
            tool_name="code_review",
            tool_description="Provide structured code review feedback",
            **kwargs,
        )


def get_deepseek_client(env, company_id=None):
    return DeepSeekClient(env, company_id)
