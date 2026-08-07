import codecs
import encodings.aliases
import re
import sys

import babel.core

import odoo


def patch_module() -> None:
    patch_evented()
    patch_codecs()


odoo.evented = False


def patch_evented() -> None:
    if odoo.evented or not (len(sys.argv) > 1 and sys.argv[1] == "evented"):
        return
    sys.argv.remove("evented")
    odoo.evented = True


def patch_codecs() -> None:

    encodings.aliases.aliases["874"] = "cp874"
    encodings.aliases.aliases["windows_874"] = "cp874"

    iso8859_8 = codecs.lookup("iso8859_8")
    iso8859_8ie_re = re.compile(r"iso[-_]?8859[-_]8[-_]?[ei]", re.IGNORECASE)
    codecs.register(
        lambda charset: iso8859_8 if iso8859_8ie_re.match(charset) else None
    )

    babel.core.LOCALE_ALIASES["nb"] = "nb_NO"
