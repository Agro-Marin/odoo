CHAT_TIMEOUT = 25
TRANSCRIBE_TIMEOUT = 30

PROVIDERS = {
    "groq": {
        "label": "Groq",
        "wire": "openai",
        "chat_service": "groq",
        "chat_path": "/chat/completions",
        "chat_model": "llama-3.3-70b-versatile",
        "vision": True,
        "vision_model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "audio": "whisper",
        "audio_service": "groq",
        "audio_path": "/audio/transcriptions",
        "audio_model": "whisper-large-v3-turbo",
    },
    "gemini": {
        "label": "Google Gemini",
        "wire": "openai",
        "chat_service": "gemini_openai",
        "chat_path": "/chat/completions",
        "chat_model": "gemini-3.5-flash-lite",
        "extra": {"reasoning_effort": "low"},
        "min_max_tokens": 2000,
        "vision": True,
        "audio": "gemini_inline",
        "audio_service": "gemini",
        "audio_path": "/models/{model}:generateContent",
        "audio_model": "gemini-flash-lite-latest",
        "audio_timeout": 90,
    },
    "openai": {
        "label": "OpenAI",
        "wire": "openai",
        "chat_service": "openai",
        "chat_path": "/chat/completions",
        "chat_model": "gpt-4o-mini",
        "vision": True,
        "audio": "whisper",
        "audio_service": "openai",
        "audio_path": "/audio/transcriptions",
        "audio_model": "whisper-1",
    },
    "deepseek": {
        "label": "DeepSeek",
        "wire": "openai",
        "chat_service": "deepseek",
        "chat_path": "/chat/completions",
        "chat_model": "deepseek-chat",
        "audio": None,
    },
    "moonshot": {
        "label": "Moonshot (Kimi)",
        "wire": "openai",
        "chat_service": "moonshot",
        "chat_path": "/chat/completions",
        "chat_model": "kimi-k3",
        "extra": {"temperature": 1},
        "min_max_tokens": 2000,
        "chat_timeout": 60,
        "audio": None,
    },
    "claude": {
        "label": "Anthropic (Claude)",
        "wire": "anthropic",
        "chat_service": "claude",
        "chat_path": "/messages",
        "chat_model": "claude-sonnet-5",
        "vision": True,
        "audio": None,
    },
}


def provider_selection():
    return [(code, spec["label"]) for code, spec in PROVIDERS.items()]


def build_openai_content(text, images):
    if not images:
        return text
    return [
        {"type": "text", "text": text},
        *(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mimetype};base64,{data}"},
            }
            for data, mimetype in images
        ),
    ]


def build_anthropic_content(text, images):
    if not images:
        return text
    return [
        {"type": "text", "text": text},
        *(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mimetype,
                    "data": data,
                },
            }
            for data, mimetype in images
        ),
    ]


def read_openai_content(payload):
    if not isinstance(payload, dict):
        return "", f"expected a JSON object, got {type(payload).__name__}"
    try:
        choice = payload["choices"][0]
    except KeyError, IndexError, TypeError:
        return "", "response carried no choices"
    content = (choice.get("message") or {}).get("content") or ""
    finish = choice.get("finish_reason")
    if not content:
        return "", f"empty content (finish_reason={finish})"
    if finish == "length":
        return "", f"truncated at the token cap (finish_reason={finish})"
    return content, None


def read_anthropic_content(payload):
    if not isinstance(payload, dict):
        return "", f"expected a JSON object, got {type(payload).__name__}"
    blocks = payload.get("content")
    if not isinstance(blocks, list):
        return "", "response carried no content blocks"
    text = "".join(
        block.get("text") or ""
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )
    stop = payload.get("stop_reason")
    if not text:
        return "", f"no text blocks (stop_reason={stop})"
    if stop == "max_tokens":
        return "", f"truncated at the token cap (stop_reason={stop})"
    return text, None


def build_whisper_form(audio_model, language="es", prompt=None):
    form = {
        "response_format": "text",
        "model": audio_model,
        "language": language,
    }
    if prompt:
        form["prompt"] = prompt
    return form


def read_whisper_transcript(payload):
    if payload is None:
        return None, "no response"
    if not isinstance(payload, str):
        return None, f"expected text, got {type(payload).__name__}"
    text = payload.strip()
    if not text:
        return None, "empty transcript"
    return text, None


def audio_mimetype(filename):
    lowered = (filename or "").lower()
    for suffix, mimetype in (
        (".mp3", "audio/mpeg"),
        (".m4a", "audio/mp4"),
        (".mp4", "audio/mp4"),
        (".wav", "audio/wav"),
        (".flac", "audio/flac"),
        (".webm", "audio/webm"),
    ):
        if lowered.endswith(suffix):
            return mimetype
    return "audio/ogg"
