import logging

from .base import BaseAIClient
from odoo.addons.api_transport.tools.exceptions import CommError

_logger = logging.getLogger(__name__)


class DeepgramClient(BaseAIClient):
    ENDPOINT_CODE = "deepgram"

    FALLBACK_MODEL = "nova-3"

    MODELS = {
        "nova-3": "Latest and most accurate model (2025) - 54.2% WER reduction",
        "nova-3-general": "Nova-3 general purpose variant",
        "nova-3-medical": "Nova-3 medical transcription variant",
        "flux-general-en": "Conversational voice agent model (English-only, uses /v2/listen)",
        "nova-2": "Previous generation accurate model",
        "nova": "Fast and accurate general-purpose model",
        "enhanced": "Improved version of base model",
        "base": "Standard model for general transcription",
        "whisper": "OpenAI Whisper model via Deepgram",
    }

    TTS_VOICES = {
        "aura-2-amalthea-en": "Female",
        "aura-2-andromeda-en": "Female",
        "aura-2-asteria-en": "Female",
        "aura-2-athena-en": "Female",
        "aura-2-aurora-en": "Female",
        "aura-2-callista-en": "Female",
        "aura-2-cora-en": "Female",
        "aura-2-cordelia-en": "Female",
        "aura-2-delia-en": "Female",
        "aura-2-electra-en": "Female",
        "aura-2-harmonia-en": "Female",
        "aura-2-helena-en": "Female",
        "aura-2-hera-en": "Female",
        "aura-2-iris-en": "Female",
        "aura-2-janus-en": "Female",
        "aura-2-juno-en": "Female",
        "aura-2-luna-en": "Female",
        "aura-2-minerva-en": "Female",
        "aura-2-ophelia-en": "Female",
        "aura-2-pandora-en": "Female",
        "aura-2-phoebe-en": "Female",
        "aura-2-selene-en": "Female",
        "aura-2-thalia-en": "Female",
        "aura-2-theia-en": "Female",
        "aura-2-vesta-en": "Female",
        "aura-2-apollo-en": "Male",
        "aura-2-arcas-en": "Male",
        "aura-2-aries-en": "Male",
        "aura-2-atlas-en": "Male",
        "aura-2-draco-en": "Male",
        "aura-2-hermes-en": "Male",
        "aura-2-hyperion-en": "Male",
        "aura-2-jupiter-en": "Male",
        "aura-2-mars-en": "Male",
        "aura-2-neptune-en": "Male",
        "aura-2-odysseus-en": "Male",
        "aura-2-orion-en": "Male",
        "aura-2-orpheus-en": "Male",
        "aura-2-pluto-en": "Male",
        "aura-2-saturn-en": "Male",
        "aura-2-zeus-en": "Male",
        "aura-2-celeste-es": "Female, Spanish",
        "aura-2-estrella-es": "Female, Spanish",
        "aura-2-nestor-es": "Male, Spanish",
    }

    LANGUAGES = [
        "en",
        "en-US",
        "en-GB",
        "en-AU",
        "en-NZ",
        "en-IN",
        "es",
        "es-419",
        "es-ES",
        "fr",
        "fr-CA",
        "de",
        "it",
        "pt",
        "pt-BR",
        "nl",
        "pl",
        "ru",
        "tr",
        "uk",
        "ja",
        "ko",
        "zh",
        "zh-CN",
        "zh-TW",
        "hi",
        "id",
        "ms",
        "th",
        "vi",
        "ar",
        "he",
        "sv",
        "da",
        "no",
        "fi",
    ]

    def _get_listen_endpoint(self, model):
        if "flux" in model.lower():
            _logger.warning(
                "Flux model '%s' requires /v2/listen endpoint. Current implementation uses /v1 base. This may not work correctly. Consider using nova-3 instead.",
                model,
            )
            return "/listen"
        return "/listen"

    def _validate_response(self, response):
        if not isinstance(response, dict):
            raise CommError(
                f"Invalid response type: expected dict but got {type(response).__name__}",
            )

        result = response.get("body")
        if result is None:
            text_preview = response.get("text", "")[:200]
            _logger.error("Deepgram response missing body: %s", text_preview)
            raise CommError(
                f"Invalid API response format: expected JSON body but got {text_preview}",
            )

        if not isinstance(result, dict):
            raise CommError(
                f"Invalid API response: expected dict but got {type(result).__name__}",
            )

        return result

    _PASSTHROUGH_PARAMS = ("model", "language", "alternatives")

    _BOOLEAN_PARAMS = (
        "paragraphs",
        "utterances",
        "detect_entities",
        "sentiment",
        "intents",
        "detect_language",
        "profanity_filter",
        "numerals",
        "multichannel",
        "smart_format",
        "filler_words",
    )

    _LIST_PARAMS = ("search", "redact", "replace")

    _SUMMARIZE_VALUES = {True: "true", False: "false", "v2": "v2", "true": "true"}

    _KEYTERM_FAMILIES = ("nova-3", "flux")

    def _build_transcription_params(self, **kwargs):
        params = {}

        for name in self._PASSTHROUGH_PARAMS:
            if name in kwargs:
                params[name] = kwargs[name]

        if kwargs.get("punctuate", True):
            params["punctuate"] = "true"

        for name in self._BOOLEAN_PARAMS:
            if kwargs.get(name):
                params[name] = "true"

        for name in self._LIST_PARAMS:
            if kwargs.get(name) and isinstance(kwargs[name], list):
                params[name] = kwargs[name]

        if "timestamps" in kwargs:
            params["timestamps"] = "true" if kwargs["timestamps"] else "false"

        if kwargs.get("diarize"):
            params["diarize"] = "true"
            if "diarize_version" in kwargs:
                params["diarize_version"] = kwargs["diarize_version"]

        if kwargs.get("topics") or kwargs.get("detect_topics"):
            params["topics"] = "true"

        if kwargs.get("summarize"):
            value = kwargs["summarize"]
            resolved = self._SUMMARIZE_VALUES.get(value)
            if resolved is None:
                _logger.warning(
                    "Invalid summarize value: %s. Expected True, False, 'v2', or 'true'",
                    value,
                )
                resolved = "true"
            params["summarize"] = resolved

        params.update(self._build_keyword_params(**kwargs))

        return params

    def _build_keyword_params(self, **kwargs):
        model_name = kwargs.get("model", "nova-3").lower()

        if any(family in model_name for family in self._KEYTERM_FAMILIES):
            keyterm = kwargs.get("keyterm")
            if isinstance(keyterm, list):
                return {"keyterm": keyterm}
            if isinstance(keyterm, str) and keyterm:
                return {"keyterm": [keyterm]}
            return {}

        keywords = kwargs.get("keywords")
        if keywords and isinstance(keywords, list):
            return {"keywords": keywords}
        return {}

    def transcribe_url(self, audio_url, model=None, **kwargs):
        model = self._resolve_model(model)
        if model not in self.MODELS:
            _logger.warning(
                "Model '%s' not in known models %s. This may cause API errors.",
                model,
                list(self.MODELS.keys()),
            )

        params = self._build_transcription_params(model=model, **kwargs)

        payload = {"url": audio_url}

        response = self._client.post("/listen", json=payload, params=params)
        return self._validate_response(response)

    def transcribe_file(self, audio_data, mimetype=None, model=None, **kwargs):
        model = self._resolve_model(model)
        if model not in self.MODELS:
            _logger.warning(
                "Model '%s' not in known models %s",
                model,
                list(self.MODELS.keys()),
            )

        params = self._build_transcription_params(model=model, **kwargs)

        headers = {}
        if mimetype:
            headers["Content-Type"] = mimetype
        else:
            headers["Content-Type"] = "application/octet-stream"
            _logger.warning(
                "No mimetype specified for file upload. Using application/octet-stream. "
                "For best results, specify the correct audio MIME type.",
            )

        response = self._client.post(
            "/listen",
            data=audio_data,
            params=params,
            headers=headers,
        )
        return self._validate_response(response)

    def transcribe_with_diarization(self, audio_url, model=None, **kwargs):
        model = self._resolve_model(model)
        kwargs["diarize"] = True
        kwargs["utterances"] = True
        return self.transcribe_url(audio_url, model=model, **kwargs)

    def transcribe_with_intelligence(
        self,
        audio_url,
        model=None,
        summarize=True,
        topics=True,
        sentiment=True,
        detect_entities=True,
        intents=True,
        **kwargs,
    ):
        model = self._resolve_model(model)
        kwargs.update(
            {
                "summarize": summarize,
                "topics": topics,
                "sentiment": sentiment,
                "detect_entities": detect_entities,
                "intents": intents,
            },
        )
        return self.transcribe_url(audio_url, model=model, **kwargs)

    def transcribe_multilingual(self, audio_url, model=None, **kwargs):
        model = self._resolve_model(model)
        kwargs["detect_language"] = True
        return self.transcribe_url(audio_url, model=model, **kwargs)

    def transcribe_with_redaction(
        self,
        audio_url,
        redact_pii=True,
        model=None,
        **kwargs,
    ):
        model = self._resolve_model(model)
        if redact_pii:
            kwargs["redact"] = [
                "pci",
                "ssn",
                "numbers",
                "email",
                "phone_number",
                "name",
            ]
        return self.transcribe_url(audio_url, model=model, **kwargs)

    def transcribe_with_search(self, audio_url, search_terms, model=None, **kwargs):
        model = self._resolve_model(model)
        kwargs["search"] = search_terms
        return self.transcribe_url(audio_url, model=model, **kwargs)

    def transcribe_with_keywords(self, audio_url, keywords, model=None, **kwargs):
        model = self._resolve_model(model)
        if "nova-3" in model.lower() or "flux" in model.lower():
            kwargs["keyterm"] = keywords
        else:
            kwargs["keywords"] = keywords

        return self.transcribe_url(audio_url, model=model, **kwargs)

    def streaming_transcribe(self, model=None, **kwargs):
        model = self._resolve_model(model)
        params = self._build_transcription_params(model=model, **kwargs)

        if kwargs.get("interim_results"):
            params["interim_results"] = "true"

        if kwargs.get("endpointing"):
            params["endpointing"] = kwargs["endpointing"]

        if kwargs.get("vad_events"):
            params["vad_events"] = "true"

        base_url = "wss://api.deepgram.com/v1/listen"
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])

        return {
            "websocket_url": f"{base_url}?{query_string}",
            "params": params,
            "connection_type": "websocket",
            "protocol": "wss",
        }

    def text_to_speech(self, text, voice="aura-2-asteria-en", model=None, **kwargs):
        if voice not in self.TTS_VOICES:
            _logger.warning(
                "Voice '%s' not in known voices %s",
                voice,
                list(self.TTS_VOICES.keys()),
            )

        params = {"model": voice}

        if kwargs.get("encoding"):
            params["encoding"] = kwargs["encoding"]

        if kwargs.get("sample_rate"):
            params["sample_rate"] = kwargs["sample_rate"]

        if kwargs.get("container"):
            params["container"] = kwargs["container"]

        del text, voice, kwargs, params
        raise CommError(
            "Deepgram text_to_speech is not supported through OutboundAPIClient yet; "
            "binary response bodies are not exposed. See t20851 follow-up.",
        )

    def text_to_speech_stream(self, text, voice="aura-2-asteria-en", **kwargs):
        if voice not in self.TTS_VOICES:
            _logger.warning(
                "Voice '%s' not in known voices %s",
                voice,
                list(self.TTS_VOICES.keys()),
            )

        params = {"model": voice}

        if kwargs.get("encoding"):
            params["encoding"] = kwargs["encoding"]

        del text, voice, kwargs, params
        raise CommError(
            "Deepgram text_to_speech_stream is not supported through "
            "OutboundAPIClient yet; streaming responses are not exposed. "
            "See t20851 follow-up.",
        )
        yield  # pragma: no cover

    def analyze_audio(self, audio_url, model=None, **kwargs):
        model = self._resolve_model(model)
        result = self.transcribe_with_intelligence(
            audio_url,
            model=model,
            diarize=True,
            **kwargs,
        )

        channels = result.get("results", {}).get("channels", [])
        if not channels:
            return {"error": "No transcription data available"}

        alternatives = channels[0].get("alternatives", [])
        if not alternatives:
            return {"error": "No transcription alternatives"}

        transcript = alternatives[0].get("transcript", "")

        return {
            "transcript": transcript,
            "summary": result.get("results", {}).get("summary", {}).get("short", ""),
            "topics": [
                t.get("topic")
                for t in result.get("results", {}).get("topics", {}).get("segments", [])
            ],
            "overall_sentiment": self._calculate_overall_sentiment(result),
            "entities": result.get("results", {}).get("entities", []),
            "intents": result.get("results", {}).get("intents", {}),
            "speaker_count": len(
                {
                    u.get("speaker")
                    for u in result.get("results", {}).get("utterances", [])
                },
            ),
            "duration": result.get("metadata", {}).get("duration", 0),
            "language": channels[0].get("detected_language", "unknown"),
            "raw_result": result,
        }

    def _calculate_overall_sentiment(self, result):
        sentiments = result.get("results", {}).get("sentiments", {}).get("segments", [])

        if not sentiments:
            return "neutral"

        positive_count = sum(1 for s in sentiments if s.get("sentiment") == "positive")
        negative_count = sum(1 for s in sentiments if s.get("sentiment") == "negative")

        total = len(sentiments)
        if total == 0:
            return "neutral"

        positive_ratio = positive_count / total
        negative_ratio = negative_count / total

        if positive_ratio > 0.6:
            return "positive"
        if negative_ratio > 0.6:
            return "negative"
        return "neutral"

    def get_usage(self, result):
        metadata = result.get("metadata", {})

        return {
            "duration": metadata.get("duration", 0),
            "channels": metadata.get("channels", 1),
            "model_uuid": metadata.get("model_uuid", ""),
            "model_name": metadata.get("model_info", {}).get("name", ""),
            "request_id": metadata.get("request_id", ""),
        }

    def get_available_models(self):
        return self.MODELS.copy()

    def get_available_voices(self):
        return self.TTS_VOICES.copy()

    def get_supported_languages(self):
        return self.LANGUAGES.copy()

    def transcribe_conversation(
        self,
        audio_url,
        model=None,
        extract_insights=True,
        **kwargs,
    ):
        model = self._resolve_model(model)
        result = self.transcribe_with_intelligence(
            audio_url,
            model=model,
            diarize=True,
            **kwargs,
        )

        utterances = result.get("results", {}).get("utterances", [])
        sentiments_data = (
            result.get("results", {}).get("sentiments", {}).get("segments", [])
        )

        turns = []
        for utterance in utterances:
            turn_data = {
                "speaker": utterance.get("speaker", 0),
                "text": utterance.get("transcript", ""),
                "start": utterance.get("start", 0),
                "end": utterance.get("end", 0),
                "confidence": utterance.get("confidence", 0),
                "sentiment": self._get_sentiment_for_timerange(
                    sentiments_data,
                    utterance.get("start", 0),
                    utterance.get("end", 0),
                ),
            }
            turns.append(turn_data)

        conversation_data = {
            "turns": turns,
            "speaker_count": len({t["speaker"] for t in turns}),
            "duration": result.get("metadata", {}).get("duration", 0),
        }

        if extract_insights:
            conversation_data.update(
                {
                    "summary": result.get("results", {})
                    .get("summary", {})
                    .get("short", ""),
                    "topics": [
                        t.get("topic")
                        for t in result.get("results", {})
                        .get("topics", {})
                        .get("segments", [])
                    ],
                    "entities": result.get("results", {}).get("entities", []),
                    "intents": result.get("results", {}).get("intents", {}),
                },
            )

        return conversation_data

    def _get_sentiment_for_timerange(self, sentiments, start, end):
        relevant_sentiments = []
        for seg in sentiments:
            seg_start = seg.get("start", 0)
            seg_end = seg.get("end", 0)

            if seg_start <= end and seg_end >= start:
                relevant_sentiments.append(seg.get("sentiment", "neutral"))

        if not relevant_sentiments:
            return "neutral"

        from collections import Counter

        sentiment_counts = Counter(relevant_sentiments)
        return sentiment_counts.most_common(1)[0][0]


def get_deepgram_client(env, company_id=None):
    return DeepgramClient(env, company_id)
