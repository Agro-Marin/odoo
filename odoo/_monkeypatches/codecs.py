import codecs
import re


def patch_module() -> None:
    iso8859_8 = codecs.lookup("iso8859_8")
    iso8859_8ie_re = re.compile(r"iso[-_]?8859[-_]?8[-_]?[ei]\Z", re.IGNORECASE)
    codecs.register(
        lambda charset: iso8859_8 if iso8859_8ie_re.match(charset) else None
    )
