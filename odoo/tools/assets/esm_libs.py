import hashlib
import logging
import posixpath
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple

from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.tools.misc import file_path

from .esm_graph import _get_import_specifiers
from .esm_registry import external_libs

__all__ = [
    "LIB_URL_PREFIX",
    "ServedLib",
    "invalidate_served_libs",
    "lib_closure",
    "lib_unique",
    "served_external_libs",
    "served_lib_content",
    "served_lib_files",
]

LIB_URL_PREFIX = "/web/assets/lib/"

_TRANSFORM_TAG = b"minify-keep-names-1"

_libs_log = get_asset_logger("bundle")


class ServedLib(NamedTuple):
    spec: str
    declared_url: str
    unique: str
    files: Mapping


class _ServedLibs(NamedTuple):
    by_spec: Mapping
    by_served_url: Mapping


_lock = threading.Lock()
_cache: list = [None]


def invalidate_served_libs() -> None:
    with _lock:
        _cache[0] = None
        _content_cache.clear()


def _static_root(url: str) -> str | None:
    module, static, rest = url.lstrip("/").partition("/static/")
    if not (module and static and rest) or "/" in module:
        return None
    return f"/{module}/static/"


def _resolve_url(url: str) -> Path | None:
    try:
        return Path(file_path(url.lstrip("/")))
    except FileNotFoundError, ValueError, OSError:
        return None


def lib_closure(declared_url: str) -> dict[str, Path]:
    root = _static_root(declared_url)
    path = _resolve_url(declared_url)
    if root is None or path is None:
        return {}
    files: dict[str, Path] = {}
    pending = [(declared_url, path)]
    while pending:
        url, path = pending.pop()
        if url in files:
            continue
        files[url] = path
        try:
            source = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        for spec in sorted(_get_import_specifiers(source)):
            if not isinstance(spec, str) or not spec.startswith(("./", "../")):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(url), spec))
            if not target.startswith(root):
                continue
            target_path = _resolve_url(target)
            if target_path is not None and target not in files:
                pending.append((target, target_path))
    return files


def lib_unique(files: Mapping[str, Path]) -> str:
    digest = hashlib.sha256(_TRANSFORM_TAG)
    for url in sorted(files):
        digest.update(url.encode())
        digest.update(b"\0")
        digest.update(files[url].read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def served_lib_url(unique: str, url: str) -> str:
    return f"{LIB_URL_PREFIX}{unique}{url}"


def _merge_overlapping(closures: Mapping[str, dict[str, Path]]) -> dict[str, dict]:
    groups: list[dict[str, Path]] = []
    owner: dict[str, int] = {}
    for declared_url, files in closures.items():
        hit = sorted({owner[url] for url in files if url in owner}, reverse=True)
        merged = dict(files)
        for index in hit:
            merged.update(groups[index])
            groups[index] = {}
        groups.append(merged)
        for url in merged:
            owner[url] = len(groups) - 1
        owner[declared_url] = len(groups) - 1
    return {declared: groups[owner[declared]] for declared in closures}


def _prepare_served_libs() -> _ServedLibs:
    by_spec: dict[str, ServedLib] = {}
    by_served_url: dict[str, tuple[ServedLib, str]] = {}
    closures: dict[str, dict[str, Path]] = {}
    unresolved = []
    for spec, declared_url in external_libs().items():
        if declared_url not in closures:
            closures[declared_url] = lib_closure(declared_url)
        if not closures[declared_url]:
            unresolved.append(spec)
    groups = _merge_overlapping(
        {url: files for url, files in closures.items() if files}
    )
    uniques: dict[int, str] = {}
    for spec, declared_url in external_libs().items():
        files = groups.get(declared_url)
        if not files:
            continue
        unique = uniques.get(id(files))
        if unique is None:
            unique = uniques[id(files)] = lib_unique(files)
        lib = ServedLib(spec, declared_url, unique, MappingProxyType(files))
        by_spec[spec] = lib
        for url in files:
            by_served_url.setdefault(served_lib_url(unique, url), (lib, url))
    log_event(
        _libs_log,
        logging.INFO,
        "served_libs_built",
        libs=len(by_spec),
        groups=len(uniques),
        files=len(by_served_url),
        unresolved=len(unresolved),
    )
    return _ServedLibs(MappingProxyType(by_spec), MappingProxyType(by_served_url))


def _served_libs() -> _ServedLibs:
    if _cache[0] is None:
        with _lock:
            if _cache[0] is None:
                _cache[0] = _prepare_served_libs()
    return _cache[0]


def served_external_libs() -> Mapping[str, str]:
    served = _served_libs().by_spec
    return MappingProxyType(
        {
            spec: (served_lib_url(served[spec].unique, url) if spec in served else url)
            for spec, url in external_libs().items()
        }
    )


def served_lib_files() -> Mapping[str, tuple[ServedLib, str]]:
    return _served_libs().by_served_url


_content_cache: dict[str, bytes] = {}


def served_lib_content(served_url: str, build: Callable[[], bytes]) -> bytes:
    content = _content_cache.get(served_url)
    if content is None:
        content = _content_cache[served_url] = build()
    return content
