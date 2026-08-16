from .base import BaseAIClient


class GeminiClient(BaseAIClient):
    ENDPOINT_CODE = "gemini"

    FALLBACK_MODEL = "gemini-2.0-flash-exp"

    def generate_content(
        self,
        contents,
        model=None,
        generation_config=None,
        safety_settings=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        if isinstance(contents, str):
            contents = [{"parts": [{"text": contents}]}]
        elif isinstance(contents, list) and len(contents) > 0:
            if isinstance(contents[0], dict) and "role" in contents[0]:
                formatted_contents = []
                for msg in contents:
                    role = "user" if msg["role"] == "user" else "model"
                    formatted_contents.append(
                        {"role": role, "parts": [{"text": msg["content"]}]}
                    )
                contents = formatted_contents

        payload = {"contents": contents, **kwargs}

        if generation_config:
            payload["generationConfig"] = generation_config

        if safety_settings:
            payload["safetySettings"] = safety_settings

        response = self._client.post(f"/models/{model}:generateContent", json=payload)
        return response["body"]

    def simple_completion(self, prompt, model=None, **kwargs):
        model = self._resolve_model(model)
        generation_config = {}
        if "temperature" in kwargs:
            generation_config["temperature"] = kwargs.pop("temperature")
        if "max_tokens" in kwargs:
            generation_config["maxOutputTokens"] = kwargs.pop("max_tokens")
        if "top_p" in kwargs:
            generation_config["topP"] = kwargs.pop("top_p")

        result = self.generate_content(
            prompt,
            model=model,
            generation_config=generation_config or None,
            **kwargs,
        )

        if (
            result.get("candidates")
            and len(result["candidates"]) > 0
            and result["candidates"][0].get("content")
        ):
            parts = result["candidates"][0]["content"].get("parts", [])
            if parts and len(parts) > 0:
                return parts[0].get("text", "")

        return ""

    def chat_completion(
        self,
        messages,
        model=None,
        temperature=1.0,
        **kwargs,
    ):
        model = self._resolve_model(model)
        generation_config = {"temperature": temperature}

        if "max_tokens" in kwargs:
            generation_config["maxOutputTokens"] = kwargs.pop("max_tokens")

        result = self.generate_content(
            messages,
            model=model,
            generation_config=generation_config,
            **kwargs,
        )

        if (
            result.get("candidates")
            and len(result["candidates"]) > 0
            and result["candidates"][0].get("content")
        ):
            parts = result["candidates"][0]["content"].get("parts", [])
            if parts and len(parts) > 0:
                return parts[0].get("text", "")

        return ""

    def vision_completion(
        self,
        prompt,
        image_data,
        media_type="image/jpeg",
        model=None,
        **kwargs,
    ):
        return self.multimodal_completion(
            text=prompt,
            image_data=f"data:{media_type};base64,{image_data}",
            model=model,
            **kwargs,
        )

    def multimodal_completion(
        self,
        text,
        image_data=None,
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        parts = [{"text": text}]

        if image_data:
            if isinstance(image_data, str) and (
                image_data.startswith("data:") or len(image_data) > 1000
            ):
                if image_data.startswith("data:"):
                    mime_type = image_data.split(";")[0].split(":")[1]
                    data = image_data.split(",")[1]
                else:
                    mime_type = "image/jpeg"
                    data = image_data

                parts.append({"inline_data": {"mime_type": mime_type, "data": data}})

        contents = [{"parts": parts}]

        result = self.generate_content(contents, model=model, **kwargs)

        if (
            result.get("candidates")
            and len(result["candidates"]) > 0
            and result["candidates"][0].get("content")
        ):
            response_parts = result["candidates"][0]["content"].get("parts", [])
            if response_parts and len(response_parts) > 0:
                return response_parts[0].get("text", "")

        return ""

    def streaming_completion(
        self,
        contents,
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        if isinstance(contents, str):
            contents = [{"parts": [{"text": contents}]}]

        payload = {"contents": contents, **kwargs}

        response = self._client.post(
            f"/models/{model}:streamGenerateContent",
            json=payload,
            stream=True,
            raw=True,
        )

        for line in response.iter_lines():
            if line:
                yield line.decode("utf-8")


def get_gemini_client(env, company_id=None):
    return GeminiClient(env, company_id)
