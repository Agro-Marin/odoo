import codecs
import encodings.aliases
import re


def patch_module() -> None:
    """Resolve charset labels that reach us from mail and imports but not CPython.

    `encodings.aliases` gets the Thai codepage under the two spellings a MIME
    header uses for it.  The ISO-8859-8 search function covers the visual and
    logical Hebrew variants: CPython resolves `iso_8859_8_i` on its own, but
    not the separator-less `iso88598i`, and a codec search function is the only
    extension point for a name no alias table entry can spell.
    """
    encodings.aliases.aliases["874"] = "cp874"
    encodings.aliases.aliases["windows_874"] = "cp874"

    iso8859_8 = codecs.lookup("iso8859_8")
    iso8859_8ie_re = re.compile(r"iso[-_]?8859[-_]?8[-_]?[ei]\Z", re.IGNORECASE)
    codecs.register(
        lambda charset: iso8859_8 if iso8859_8ie_re.match(charset) else None
    )
