{
    "name": "Speech",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "sequence": 10,
    "summary": "Transcription and synthesis for every stored recording",
    "description": """
Speech
======

Speech is a property of a binary, not of a conversation. Anything this database
stores as audio or video can be turned into words, and any words it holds can be
turned into audio. That is the whole of this module, and it deliberately knows
no channel: it is not about calls, not about voice messages and not about
documents. Those are consumers.

Reading speech
--------------
Transcription is registered as a reader of the document layer, at ``EXPENSIVE``,
exactly as local OCR is. Two consequences follow from the cost alone and neither
is written here: a document is derived only up to the ceiling its caller sets,
so a recording is never transcribed by accident; and a dearer reader runs only
where every cheaper one answered nothing, so a file that already carries a
subtitle track is read from it rather than sent to an engine.

The transcript is therefore not a field this module invented. It is the
attachment's ``index_content`` -- the one place this database already puts "what
is inside this binary, in words" -- so a recording answers the ordinary
attachment search with no search code of its own, and every ``document_extract``
strategy that reads text starts working on recordings without being told that
audio exists. ``speech_cues`` holds the same words with their timing, for
playback and for subtitles.

Writing speech
--------------
Synthesis is a writer of the same layer, consuming ``text`` and emitting audio,
so an engine is registered exactly as a reader is and no vendor is named here.

``_speech_synthesize`` does not go through ``Document.of``, and the reason is a
real difference between the two halves. A reader carries a cost and an empty
answer falls through to the next one, so a reader that cannot run costs nothing.
A writer carries neither: ``Document.of`` takes the first writer claiming the
mimetype, and cannot see that it holds no credential. So this picks the first
engine that reports itself usable and calls it. Two guards come with that: the
built-in text writer accepts any mimetype, so with no engine installed the call
would otherwise write a UTF-8 text file and label it audio; and with two engines
installed, the one without a key would otherwise answer.

``media.segment``
-----------------
A recording arrives in pieces -- a call recorded in chunks, a long interview
split for an engine's file-size limit -- and the pieces have to be played as one
timeline. A segment is one attachment plus the milliseconds it covers, against
an owner named by ``res_model``/``res_id``. Generic on purpose: upstream ties the
same idea to one nullable foreign key per owner type behind a
``num_nonnulls(...) = 1`` constraint, so every new owner is a schema change.

Transcripts are NOT segments. They live on the attachment they describe, which
is why this module needs no flag distinguishing a media artifact from a
transcript artifact, and no exclusion of transcripts from the overlap check.

``mixin.media.timeline`` gives an owner its segments, its duration, its joined
transcript, one rolled-up state and three hooks.

No engine ships here
--------------------
This module registers no reader and no writer. ``speech_ai`` provides both on
the ``api_ai`` registry, and a local engine would be a second module beside it.
With neither installed, ``can_transcribe`` is False everywhere and the actions
say so rather than failing at a vendor call.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/ir_attachment_views.xml",
        "views/media_segment_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "speech/static/src/**/*",
        ],
    },
}
