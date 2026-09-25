{
    "name": "Voice - Chatter",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Say a note or a message into a record's chatter",
    "description": """
Voice - Chatter
===============

On a form with a chatter, "nota: llamó el cliente" opens the log-note
composer and writes the words in it, and "mensaje: …" does the same for a
message to the followers. Nothing is posted by voice: the words wait in the
composer for the user to read, correct and send, and undo takes them out.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "voice",
    ],
    "assets": {
        "web.assets_backend": [
            "voice_mail/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "voice_mail/static/tests/**/*",
        ],
    },
    "auto_install": True,
}
