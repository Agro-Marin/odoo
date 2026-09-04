from __future__ import annotations

# A synthesis call is billed per character and answered in one request, so a
# message pasted from a document would be a slow, expensive surprise rather than
# a feature. Refused with its own length rather than truncated silently.
READ_ALOUD_MAX_CHARS = 4000
