{
    "name": "Speech - Voice Commands",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Hear voice commands with this database's own speech engines",
    "description": """
Speech - Voice Commands
=======================

Gives ``voice`` a speech engine where the browser has none of its own: one
utterance, recorded while the microphone is on, is sent to this server and
transcribed at once by whichever engine ``speech`` may use for it -- a local
model, or a vendor a policy allows.

A command is short and needs its words now, so it takes neither of the paths
a recording takes: no attachment is created, no job is queued, and neither
the audio nor the words are kept. It is transcribed under its own purpose,
``speech.transcription.command``, so an administrator can allow a vendor for
commands and not for recorded calls, or the other way round; with no policy,
only a local engine hears it.

It also lets ``voice`` dictate into a form field ("dicta notas"): the field
fills in as the words arrive, through ``speech``'s dictation, until the user
stops it, and undo puts back what the field held before.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "bus",
        "speech",
        "voice",
    ],
    "assets": {
        "web.assets_backend": [
            "speech_voice/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "speech_voice/static/tests/**/*",
        ],
    },
    "auto_install": True,
}
