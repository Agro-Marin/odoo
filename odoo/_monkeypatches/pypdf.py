from zlib import decompressobj

import pypdf.filters
from pypdf.generic import DictionaryObject, NameObject


def _decompress(data: bytes) -> bytes:
    return decompressobj().decompress(data)


def _unwrapping_get(self: DictionaryObject, key: object, default: object = None):
    try:
        return self[key]
    except KeyError:
        return default


def patch_module() -> None:
    pypdf.filters.decompress = _decompress
    DictionaryObject.get = _unwrapping_get
    if hasattr(NameObject, "renumber_table"):
        NameObject.renumber_table.update(
            {
                **{chr(i): f"#{i:02X}".encode() for i in b"#()<>[]{}/%"},
                **{chr(i): f"#{i:02X}".encode() for i in range(33)},
            }
        )
