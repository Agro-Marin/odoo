"""Print every backticked span in the given docs that is meant to be a path.

"Meant to be a path" is deliberately narrow: a span ending in one of the
extensions these documents actually cite. Backticks here also carry rule names,
flags and dotted attribute references, and asserting those resolve on disk would
fail on `exact=False`.
"""

import re
import sys
from pathlib import Path

BACKTICKED = re.compile(r"`([^`\n]+)`")
EXTENSIONS = (".py", ".sh", ".md", ".yml", ".json", ".rst", ".xml", ".toml")

seen: set[str] = set()
for doc in sys.argv[1:]:
    for span in BACKTICKED.findall(Path(doc).read_text(encoding="utf-8")):
        span = span.strip()
        if " " in span or not span.endswith(EXTENSIONS):
            continue
        if span not in seen:
            seen.add(span)
            sys.stdout.write(span + "\n")
