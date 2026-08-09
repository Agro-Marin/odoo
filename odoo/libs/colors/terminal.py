"""ANSI terminal colour codes and the escape sequences that apply them.

Dependency-free by nature -- these are terminal escape sequences, not framework
vocabulary -- but they lived in ``odoo/logutils.py`` until 2026-08-09, which
made every consumer import the server's logging *configuration* module to get
them. That cost is not hypothetical: ``odoo/orm/fields/textual.py`` is Layer 1
of the ORM, and importing ``odoo.logutils`` pulls ``odoo.db``, ``odoo.release``
and ``odoo.tools`` in at import time, for four integers and a format string.
"""

from typing import Final

__all__ = [
    "BLACK",
    "BLUE",
    "BOLD_SEQ",
    "COLOR_PATTERN",
    "COLOR_SEQ",
    "CYAN",
    "DEFAULT",
    "GREEN",
    "MAGENTA",
    "RED",
    "RESET_SEQ",
    "WHITE",
    "YELLOW",
    "colorize",
]

BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE, _NOTHING, DEFAULT = range(10)

RESET_SEQ: Final[str] = "\033[0m"
COLOR_SEQ: Final[str] = "\033[1;%dm"
BOLD_SEQ: Final[str] = "\033[1m"
COLOR_PATTERN: Final[str] = f"{COLOR_SEQ}{COLOR_SEQ}%s{RESET_SEQ}"


def colorize(text: str, fg: int = DEFAULT, bg: int = DEFAULT) -> str:
    """Wrap *text* in the escape sequences for *fg* on *bg*.

    The ``30 +`` / ``40 +`` offsets are the ANSI foreground and background
    ranges. Every call site open-coded them against ``COLOR_PATTERN``, which is
    why the pattern's three ``%s`` slots and their order had to be remembered
    at each one.
    """
    return COLOR_PATTERN % (30 + fg, 40 + bg, text)
