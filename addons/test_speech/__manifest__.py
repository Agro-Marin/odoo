{
    "name": "Speech Tests",
    "version": "19.0.1.0.0",
    "category": "Hidden/Tests",
    "sequence": 9876,
    "summary": "Test models and suites for the speech layer",
    "description": """
Speech Tests
============

A recording owner with no business meaning, so ``mixin.media.timeline`` and the
transcription pipeline are tested against a consumer that exists only to be one.
The engines are stubbed at the document layer, which is the same seam the real
ones register on, so a suite proves the wiring without a key or a network call.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "speech",
        # The suites below stub the engines at the document layer, so they do
        # not need these to pass -- the lane does. `integration_tests.yml`
        # gives each suite its own database and refuses a spec naming several
        # modules that are not one closure, so a layer of six modules is only
        # reachable from one lane if one module pulls it. This is that module.
        "mail_speech",
        "speech_ai",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/speech_test_recording_rules.xml",
    ],
}
