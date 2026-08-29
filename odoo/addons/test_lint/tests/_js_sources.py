import functools
import re
from pathlib import Path

from odoo.modules import Manifest

STATIC_IMPORT_RE = re.compile(
    r"""(?:^|[\s;}])(?:import|export)\s+(?:[^'"()]*?\sfrom\s+)?["']([^"']+)["']""",
    re.MULTILINE,
)
DYNAMIC_IMPORT_RE = re.compile(r"""\bimport\(\s*["']([^"']+)["']\s*\)""")
COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


@functools.cache
def addon_js() -> tuple[tuple[str, Path, str], ...]:
    out = []
    for manifest in Manifest.all_addon_manifests():
        static_root = Path(manifest.path) / "static"
        if not static_root.is_dir():
            continue
        for path in sorted(static_root.rglob("*.js")):
            try:
                out.append((manifest.name, path, path.read_text(encoding="utf-8")))
            except OSError, UnicodeDecodeError:
                continue
    return tuple(out)


@functools.cache
def addon_js_outside_lib() -> tuple[tuple[str, Path, str], ...]:
    return tuple(
        (addon, path, source)
        for addon, path, source in addon_js()
        if not _under_static_lib(addon, path)
    )


def _under_static_lib(addon: str, path: Path) -> bool:
    parts = path.as_posix().split("/static/", 1)
    return len(parts) == 2 and parts[1].split("/", 1)[0] == "lib"


def specifiers(source: str, *, strip_comments: bool = False) -> set[str]:
    code = COMMENT_RE.sub(" ", source) if strip_comments else source
    return set(STATIC_IMPORT_RE.findall(code)) | set(DYNAMIC_IMPORT_RE.findall(code))


def module_key(addon: str, path: Path) -> str | None:
    parts = path.as_posix().split("/static/", 1)
    return f"{addon}/{parts[1].removesuffix('.js')}" if len(parts) == 2 else None
