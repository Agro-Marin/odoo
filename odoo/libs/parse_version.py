"""Version parsing utilities from setuptools (version 0.6c8).

http://peak.telecommunity.com/DevCenter/PkgResources#parsing-utilities
"""

__all__ = ["parse_version"]

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

component_re = re.compile(r"(\d+ | [a-z]+ | \.| -)", re.VERBOSE)
replace = {
    "pre": "c",
    "preview": "c",
    "-": "final-",
    "_": "final-",
    "rc": "c",
    "dev": "@",
    "saas": "",
    "~": "",
}.get


def _parse_version_parts(s: str) -> Iterator[str]:
    for part in component_re.split(s):
        part = replace(part, part)
        if not part or part == ".":
            continue
        if part[:1] in "0123456789":
            yield part.zfill(8)  # pad for numeric comparison
        else:
            yield "*" + part

    yield "*final"  # ensure that alpha/beta/candidate are before final


def parse_version(s: str) -> tuple[str, ...]:
    """Convert a version string to a chronologically-sortable key.

    This is a rough cross between distutils' StrictVersion and LooseVersion;
    if you give it versions that would work with StrictVersion, then it behaves
    the same; otherwise it acts like a slightly-smarter LooseVersion. It is
    *possible* to create pathological version coding schemes that will fool
    this parser, but they should be very rare in practice.

    The returned value will be a tuple of strings.  Numeric portions of the
    version are padded to 8 digits so they will compare numerically, but
    without relying on how numbers compare relative to strings.  Dots are
    dropped, but dashes are retained.  Trailing zeros between alpha segments
    or dashes are suppressed, so that e.g. "2.4.0" is considered the same as
    "2.4". Alphanumeric parts are lower-cased.

    The algorithm assumes that strings like "-" and any alpha string that
    alphabetically follows "final" represents a "patch level".  So, "2.4-1"
    is assumed to be a branch or patch of "2.4", and therefore "2.4.1" is
    considered newer than "2.4-1", which in turn is newer than "2.4".

    Strings like "a", "b", "c", "alpha", "beta", "candidate" and so on (that
    come before "final" alphabetically) are assumed to be pre-release versions,
    so that the version "2.4" is considered newer than "2.4a1".

    Finally, to handle miscellaneous cases, the strings "pre", "preview", and
    "rc" are treated as if they were "c", i.e. as though they were release
    candidates, and therefore are not as new as a version string that does not
    contain them.
    """
    parts: list[str] = []
    for part in _parse_version_parts((s or "0.1").lower()):
        if part.startswith("*"):
            if part < "*final":  # remove '-' before a prerelease tag
                while parts and parts[-1] == "*final-":
                    parts.pop()
            # remove trailing zeros from each series of numeric parts
            while parts and parts[-1] == "00000000":
                parts.pop()
        parts.append(part)
    return tuple(parts)


# The ordering assertions that used to sit here behind
# ``if __name__ == "__main__"`` now live in
# ``odoo/libs/tests/test_parse_version.py``, where they actually run (and where
# ``-O`` cannot strip them, as it would have done to those bare ``assert``s).
