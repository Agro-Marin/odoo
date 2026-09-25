{
    "name": "Voice",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Speak to the web client: open apps, search, fill in forms and press buttons",
    "description": """
Voice
=====

A sentence, spoken or typed, becomes a proposal the user can see before it
runs: an app or menu to open, facets to add to the search, a value to stage in
a form field, a button to press. The words it understands are not a list kept
here; they are read from what the user is looking at -- the menus, the search
view's filters and group-bys, the form's labels and buttons -- in whatever
language those are translated to, Spanish and English both understood.

Navigation and search run at once and can be undone. A field value is staged
in the record and saved only when the user says so. A button such as Confirm,
or anything the user cannot undo, waits for an explicit confirmation naming
the record, and a sentence carrying a negation never presses one.

Speech is an input to that interpreter, not the other way round: the same
sentence typed in the command palette after ``>`` does the same thing. The
microphone listens only while the user holds it open (the systray button, or
Alt+Shift+V), through the first speech engine that is available: the
browser's own on-device recogniser, or one a module such as ``speech_voice``
registers.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "web",
    ],
    "assets": {
        "web.assets_backend": [
            "voice/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "voice/static/tests/**/*",
        ],
    },
}
