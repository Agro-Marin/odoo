{
    "name": "Voice - AI Fallback",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Let an AI model read the voice commands the grammar does not understand",
    "description": """
Voice - AI Fallback
===================

``voice`` understands a sentence by matching it against what is on screen.
When it matches nothing, this module asks a chat model, through
``gateway_ml``, which of those same things the user meant: the model is given
the sentence and a list of choice ids, and its answer is held to a schema whose
only allowed values are those ids. It cannot name a record, a field or a
button the screen does not have, and what it picks becomes the same proposal
the grammar would have made, with the same confirmations.

The purpose is ``voice.intent`` and it is sensitive: a sentence is the user's
own words about the company's data, so no vendor hears one until a policy of
the company names it. Without one, nothing is sent and a sentence the grammar
did not understand stays not understood.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "gateway_ml",
        "voice",
    ],
    "data": [
        "data/gateway_ml_purpose_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "voice_gateway_ml/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "voice_gateway_ml/static/tests/**/*",
        ],
    },
    "auto_install": True,
}
