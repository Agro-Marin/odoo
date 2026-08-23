import csv


def patch_module() -> None:
    """Admit a base64 image as a single CSV field.

    The stdlib limit is 128KiB, which any inlined image blows through, and the
    reader raises rather than truncating. 500MiB is a ceiling, not a target:
    it bounds a hostile import instead of letting it consume the process.
    """
    csv.field_size_limit(500 * 1024 * 1024)
