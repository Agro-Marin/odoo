from __future__ import annotations

import codecs

import chardet

# Bytes handed to chardet per `feed` call. Only affects how often the detector
# is asked whether it is done, not what it sees -- see `guess_encoding`.

__all__ = [
    "decode",
    "guess_encoding",
]
_ENCODING_CHUNK = 1 << 16

_BOM_MAP = {
    "utf-16le": codecs.BOM_UTF16_LE,
    "utf-16be": codecs.BOM_UTF16_BE,
    "utf-32le": codecs.BOM_UTF32_LE,
    "utf-32be": codecs.BOM_UTF32_BE,
}


def guess_encoding(data: bytes) -> str | None:
    detector = chardet.UniversalDetector()
    for start in range(0, len(data), _ENCODING_CHUNK):
        detector.feed(data[start : start + _ENCODING_CHUNK])
        if detector.done:
            break
    detector.close()
    encoding = detector.result["encoding"]
    if not encoding:
        return None
    encoding = encoding.lower()
    # Some chardet versions (2.3.0, not 3.x) answer utf-(16|32)(le|be), which
    # tells Python to keep the BOM as content. The unmarked name strips it,
    # which is what a caller decoding a document wants.
    bom = _BOM_MAP.get(encoding)
    if bom and data.startswith(bom):
        encoding = encoding[:-2]
    try:
        codecs.lookup(encoding)
    except LookupError:
        # chardet names codecs this Python cannot load -- EUC-TW and
        # ISO-2022-CN are the two seen here. A guess the caller cannot use is
        # not a guess; saying so lets them fall back instead of crashing on a
        # LookupError they did not expect from a decode.
        return None
    return encoding


def decode(data: bytes, encoding: str = "") -> str:
    """Decode ``data``, guessing the encoding when not told.

    Raises rather than substituting replacement characters: a document read as
    mojibake is worse than one that fails, because the mojibake reaches a
    record and the failure reaches a person.

    :param bytes data: the whole file
    :param str encoding: the encoding the caller already knows, if any
    :rtype: str
    :raises UnicodeDecodeError: if the encoding cannot be guessed, or does not apply
    """
    name = encoding or guess_encoding(data)
    if not name:
        raise UnicodeDecodeError(
            "undetermined", data, 0, len(data), "the encoding could not be guessed"
        )
    return data.decode(name)


def looks_like_text(text: str) -> bool:
    """Whether a decoded string is plausibly a document's text.

    A decoder will happily turn `\x00\x01\x02` into three characters and call
    it ascii, so "it decoded" is not the same as "it is text". Real text does
    not carry NUL, and does not consist mostly of the other C0 controls -- the
    same test `git` uses to decide a file is binary, which is the convention
    worth matching rather than inventing a threshold.
    """
    if not text:
        return False
    if "\x00" in text:
        return False
    control = sum(1 for c in text[:4096] if c < " " and c not in "\t\n\r\f\v")
    return control <= len(text[:4096]) // 20
