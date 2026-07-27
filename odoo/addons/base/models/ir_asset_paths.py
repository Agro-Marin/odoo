"""The bundle-content algebra behind ``ir.asset``: paths, ordering, directives.

Everything here is framework-free — no ORM, no registry, no database — so the
whole of asset resolution that is a pure function of a path definition, a list
of files and an ordered list of directives can be exercised by the standalone
pytest suite in ``odoo/addons/base/models/tests`` (Tier 1 of
``doc/coding_guidelines.rst §6``) instead of a ``TransactionCase``.

``ir_asset.py`` keeps only what genuinely needs the ORM: reading ``ir.asset``
rows, walking manifests, resolving a path definition against the filesystem,
and invalidating the cache. It hands :class:`BundleWalk` two callables and gets
a bundle back — which is why the directive algebra no longer has to be driven
through a model, a cursor and ``patch.object(type(IrAsset), "_get_paths", ...)``
to be tested.

The split follows ``ir_ui_view_name_manager``.
"""

import os
from collections.abc import Callable, Sequence
from glob import glob
from logging import getLogger
from stat import S_ISLNK
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from odoo.libs.constants import ASSET_EXTENSIONS, EXTERNAL_ASSET, ExternalAsset

_logger = getLogger(__name__)

DEFAULT_SEQUENCE = 16

APPEND_DIRECTIVE = "append"
PREPEND_DIRECTIVE = "prepend"
AFTER_DIRECTIVE = "after"
BEFORE_DIRECTIVE = "before"
REMOVE_DIRECTIVE = "remove"
REPLACE_DIRECTIVE = "replace"
INCLUDE_DIRECTIVE = "include"
DIRECTIVES_WITH_TARGET = {AFTER_DIRECTIVE, BEFORE_DIRECTIVE, REPLACE_DIRECTIVE}

FullPath = str | ExternalAsset | None


class AssetDirectiveError(ValueError):
    """A directive that cannot be applied, already attributed to its declaration.

    Subclasses ``ValueError`` because that is what the directive machinery
    raises and what callers (and the bundle tests) catch. The distinct type is
    what lets attribution happen exactly once: the innermost frame that knows
    the manifest command or ``ir.asset`` record wraps the failure, and the
    frames above re-raise it untouched instead of nesting one prefix per level
    of ``include``.
    """


class ResolvedPath(NamedTuple):
    """A path from :meth:`IrAsset._get_paths`, not yet bound to a bundle.

    ``full_path`` encodes the resolution kind: a filesystem path (static file),
    the :data:`EXTERNAL_ASSET` sentinel (external URL served as-is), or ``None``
    (attachment URL, resolved later against ir.attachment).
    """

    path: str
    full_path: FullPath
    last_modified: float | None

    @property
    def is_external(self) -> bool:
        """True for an external URL served individually (not bundled)."""
        return self.full_path is EXTERNAL_ASSET


class AssetEntry(NamedTuple):
    """One resolved asset bound to the bundle that contributed it.

    Positionally the 4-tuple ``(path, full_path, bundle, last_modified)`` that
    consumers unpack.
    """

    path: str
    full_path: FullPath
    bundle: str
    last_modified: float | None

    @property
    def is_external(self) -> bool:
        """True for an external URL served individually (not bundled)."""
        return self.full_path is EXTERNAL_ASSET


def fs2web(path: str) -> str:
    """Convert a filesystem path to a web path."""
    if os.sep == "/":
        return path
    return "/".join(path.split(os.sep))


def can_aggregate(url: str) -> bool:
    """Check whether *url* is a local path that can be bundled into an asset file.

    Returns False for external URLs (http://, //) and ``/web/content`` paths
    which must be served individually.
    """
    parsed = urlsplit(url)
    return (
        not parsed.scheme and not parsed.netloc and not url.startswith("/web/content")
    )


def is_wildcard_glob(path: str) -> bool:
    """Whether *path* is a wildcarded glob (e.g. ``/web/file[14].*``)."""
    return any(char in path for char in "*?[]")


def _is_symlink(path: str) -> bool:
    """Whether *path* is a symlink, False if it cannot be stat'd."""
    try:
        return S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def _reaches_root_without_symlink(
    directory: str, root: str, memo: dict[tuple[str, str], bool]
) -> bool:
    """Whether *directory* is reachable from *root* without crossing a symlink.

    *root* is already known to be a resolved, contained path, so only the
    components below it can escape -- which makes this a handful of memoized
    ``islink`` calls (~1 us each) instead of a ``realpath`` of the whole path
    (~11 us). Ancestors are memoized on the way up, so a whole subtree costs
    about one check per directory.

    *memo* is keyed by ``(root, directory)`` so one dict can be shared by every
    glob of a whole resolution: the answer is only meaningful relative to the
    root it was computed against.
    """
    cached = memo.get((root, directory))
    if cached is not None:
        return cached
    if directory == root:
        memo[root, directory] = True
        return True
    parent = directory.rpartition(os.sep)[0]
    if not parent or not directory.startswith(root + os.sep):
        memo[root, directory] = False
        return False
    result = not _is_symlink(directory) and _reaches_root_without_symlink(
        parent, root, memo
    )
    memo[root, directory] = result
    return result


def _glob_static_file(
    pattern: str,
    static_dir: str,
    symlink_memo: dict[tuple[str, str], bool] | None = None,
) -> list[tuple[str, float]]:
    """Glob *pattern* for static files, returning sorted ``(path, mtime)`` pairs.

    Only ``ASSET_EXTENSIONS`` files are included; sorted for deterministic
    bundle ordering. Files deleted between ``glob()`` and ``lstat()`` (e.g.
    during hot-reload) are skipped.

    Matches that leave *static_dir* are dropped. The caller only vetted the
    pattern's literal prefix, which says nothing about a symlink that a wildcard
    component expands onto: ``static/lib/*/x.js`` happily traverses
    ``static/lib/anywhere -> /etc`` and hands back a path that still *looks*
    addon-relative.

    Crossing a symlink is not itself the violation — landing outside is. A
    symlinked match is therefore resolved and re-checked, and reported under its
    real path, so a directory symlinked to a sibling inside the same ``static/``
    keeps working (as it did when the whole path was ``resolve()``d) whether a
    literal path names it or a wildcard expands onto it.

    :param symlink_memo: containment cache shared across a whole resolution;
        hundreds of patterns walk the same handful of directories, so a
        per-pattern cache re-``lstat``\\ s each of them once per pattern.
    """
    result: set[tuple[str, float]] = set()
    if symlink_memo is None:
        symlink_memo = {}
    for file in glob(pattern, recursive=True):
        if file.rsplit(".", 1)[-1] not in ASSET_EXTENSIONS:
            continue
        try:
            status = os.lstat(file)
        except OSError:
            continue
        directory = file.rpartition(os.sep)[0]
        if S_ISLNK(status.st_mode) or not _reaches_root_without_symlink(
            directory, static_dir, symlink_memo
        ):
            real = os.path.realpath(file)
            if real != static_dir and not real.startswith(static_dir + os.sep):
                _logger.warning(
                    "IrAsset: %r matched %r, which links out of the addon's "
                    "static/ directory (to %r); skipped.",
                    pattern,
                    file,
                    real,
                )
                continue
            try:
                status = os.lstat(real)
            except OSError:
                continue
            file = real
        result.add((file, status.st_mtime))
    return sorted(result)


class Anchor:
    """A position in an :class:`AssetPaths` list that survives later mutations.

    ``prepend`` puts files at the start of the segment contributed by the
    bundle being walked, which is an *index* into a list the very same walk
    keeps mutating. Held as a bare int (as it was), any earlier removal moved
    the segment out from under it: a sub-bundle that removed a file its parent
    had already appended then prepended past the end of the list, silently
    turning ``prepend`` into ``append``. :class:`AssetPaths` shifts every live
    anchor instead.
    """

    __slots__ = ("index",)

    def __init__(self, index: int) -> None:
        self.index = index

    def __repr__(self) -> str:
        return f"Anchor({self.index})"


class AssetPaths:
    """A deduplicated list of asset paths with positional operations.

    Each entry is an ``AssetEntry`` ``(path, full_path, bundle, last_modified)``;
    the ``memo`` set tracks seen paths for O(1) uniqueness. Mutating methods take
    3-element source tuples ``(path, full_path, last_modified)`` and bind them to
    *bundle*.
    """

    def __init__(self) -> None:
        self.list: list[AssetEntry] = []
        self.memo: set[str] = set()
        self.anchors: list[Anchor] = []

    def new_anchor(self) -> Anchor:
        """Return an :class:`Anchor` on the current end of the list."""
        anchor = Anchor(len(self.list))
        self.anchors.append(anchor)
        return anchor

    def release_anchor(self, anchor: Anchor) -> None:
        """Stop tracking *anchor*, whose bundle is fully walked.

        Only the anchors of bundles still on the ``include`` stack can be
        prepended to; keeping the closed ones alive would both cost a shift per
        mutation and make the boundary case (inserting exactly *at* an anchor)
        ambiguous between a dead segment and the live one.
        """
        self.anchors.remove(anchor)

    def index(self, path: str, bundle: str) -> int:
        """Return the index of *path* in the list; raise if absent."""
        return self.index_of_first([path], bundle)

    def index_of_first(self, paths: Sequence[str], bundle: str) -> int:
        """Return the index of the first of *paths* the list actually holds.

        A directive positions itself against a *target*, and a target that is a
        glob resolves to several files of which the bundle may hold any subset.
        *paths* is scanned in resolution order, not list order: the anchor is
        then decided by the target definition (which the author wrote) rather
        than by whatever order the bundle happens to have ended up in, so this
        stays what it always was — the first resolved target — and only skips
        the matches this bundle does not carry instead of failing on them.

        :raises ValueError: if none of *paths* is in the bundle, which leaves
            the requested position undefined.
        """
        for path in paths:
            if path in self.memo:
                for index, asset in enumerate(self.list):
                    if asset.path == path:
                        return index
                raise RuntimeError(
                    f"Inconsistent asset state: {path!r} in memo but not in list"
                )
        raise self._not_found(paths[0] if len(paths) == 1 else list(paths), bundle)

    def append(self, paths: Sequence[ResolvedPath], bundle: str) -> None:
        """Append *paths* to the list (skipping ones already present)."""
        self.insert(paths, bundle, len(self.list))

    def insert(self, paths: Sequence[ResolvedPath], bundle: str, index: int) -> None:
        """Insert *paths* at *index* (skipping ones already present)."""
        to_insert = []
        for path, full_path, last_modified in paths:
            if path not in self.memo:
                to_insert.append(AssetEntry(path, full_path, bundle, last_modified))
                self.memo.add(path)
        if not to_insert:
            return
        self.list[index:index] = to_insert
        for anchor in self.anchors:
            if anchor.index > index:
                anchor.index += len(to_insert)

    def remove(
        self, paths_to_remove: Sequence[ResolvedPath], bundle: str, strict: bool = True
    ) -> None:
        """Remove *paths_to_remove* from the list.

        Semantics by how many requested paths are present:

        * all present -> removed silently;
        * some present -> present ones removed; absent ones warned (IRASSET-A3)
          in strict mode, else ignored;
        * none present -> hard error in strict mode (removing a
          resolvable-but-absent path violates the contract), else no-op.

        :param strict: apply the must-be-present contract. Callers pass False
            for wildcarded removes (set subtraction against disk), where absent
            matches are expected, not stale.
        """
        requested = [path for path, _full_path, _last_modified in paths_to_remove]
        present = {path for path in requested if path in self.memo}
        if not present:
            if requested and strict:
                raise self._not_found(requested, bundle)
            return

        absent = [path for path in requested if path not in self.memo]
        if absent and strict:
            _logger.warning(
                "REMOVE in bundle %r ignored path(s) %s not present in the "
                "bundle (removed %s). The ignored paths are likely stale "
                "(renamed/deleted) or an over-matching glob.",
                bundle,
                absent,
                sorted(present),
            )
        kept = []
        dropped_indexes = []
        for index, asset in enumerate(self.list):
            if asset.path in present:
                dropped_indexes.append(index)
            else:
                kept.append(asset)
        self.list[:] = kept
        self.memo.difference_update(present)
        for anchor in self.anchors:
            anchor.index -= sum(1 for index in dropped_indexes if index < anchor.index)

    def _not_found(self, path: str | list[str], bundle: str) -> ValueError:
        """Build the error for a directive naming a path this bundle lacks."""
        return ValueError(f"File(s) {path} not found in bundle {bundle}")


class BundleFrame(NamedTuple):
    """The bundle currently being walked, and where its own segment starts.

    :param anchor: live position of the first file this bundle contributed;
        what ``prepend`` inserts at.
    :param seen: the chain of bundles that included this one.
    """

    bundle: str
    anchor: Anchor
    seen: tuple[str, ...]


class AssetDirective(NamedTuple):
    """One directive to apply, detached from where it was declared.

    A manifest command and an ``ir.asset`` row are the same instruction written
    two ways; only the blame differs. Normalising both into this shape is what
    lets the walk be a pure function: it applies directives in the order it is
    given them and never asks whether one came from a file or a table.

    :param origin: how to name the declaration if it fails, e.g. ``"the
        manifest of addon 'web'"`` -- the walk appends the bundle itself.
    """

    directive: str
    target: str | None
    path: str
    origin: str


class BundleWalk:
    """Applies bundles' directives to one :class:`AssetPaths`.

    Two callables supply everything the walk cannot know on its own:

    ``resolve(path_def)``
        turns a path definition into the files it designates *now*. In
        production this reaches the filesystem and ``ir.attachment``; a test
        can hand over a dict.
    ``directives_for(bundle)``
        yields the bundle's :class:`AssetDirective`\\ s already in application
        order (early records, then manifest commands, then late records).
        Resolving that order is the declaring side's job, not the walk's.

    The walk owns the parts that are pure algebra: cycle detection, the
    already-walked guard, anchors, and what each directive does to the list.
    """

    def __init__(
        self,
        resolve: Callable[[str], Sequence[ResolvedPath]],
        directives_for: Callable[[str], Sequence[AssetDirective]],
    ) -> None:
        self.resolve = resolve
        self.directives_for = directives_for
        self.paths = AssetPaths()
        self.walked: set[str] = set()

    def walk(self, bundle: str, seen: tuple[str, ...] = ()) -> None:
        """Apply *bundle*'s directives, recursing through ``include``.

        :param seen: the chain of bundles that included this one, so a cycle is
            reported as the path that closes it rather than as a
            ``RecursionError``
        """
        if bundle in seen:
            raise ValueError(
                f"Circular assets bundle declaration: {' > '.join([*seen, bundle])}"
            )
        if bundle in self.walked:
            _logger.debug(
                "Bundle %r already walked in this traversal; skipping re-include.",
                bundle,
            )
            return
        self.walked.add(bundle)

        frame = BundleFrame(bundle, self.paths.new_anchor(), seen)
        for directive in self.directives_for(bundle):
            self.apply(frame, directive)
        self.paths.release_anchor(frame.anchor)

    def apply(self, frame: BundleFrame, entry: AssetDirective) -> None:
        """Apply one directive, naming its declaration if it fails.

        Attribution happens exactly once: :class:`AssetDirectiveError` is
        re-raised untouched by the frames above, so an ``include`` chain reports
        the innermost declaration instead of nesting one prefix per level.
        """
        try:
            self._apply(frame, entry)
        except AssetDirectiveError:
            raise
        except ValueError as exc:
            raise AssetDirectiveError(
                f"{exc} — raised by {entry.origin}, declared for bundle "
                f"{frame.bundle!r}"
            ) from exc

    def _apply(self, frame: BundleFrame, entry: AssetDirective) -> None:
        directive, target, path_def = entry.directive, entry.target, entry.path
        bundle = frame.bundle
        if directive == INCLUDE_DIRECTIVE:
            self.walk(path_def, (*frame.seen, bundle))
            return

        asset_paths = self.paths
        paths = self.resolve(path_def)

        targets: list[str] = []
        if directive in DIRECTIVES_WITH_TARGET:
            targets = self._resolve_targets(directive, target, path_def, bundle)
            if not targets:
                return

        if directive == APPEND_DIRECTIVE:
            asset_paths.append(paths, bundle)
        elif directive == PREPEND_DIRECTIVE:
            self._warn_stranded(directive, paths, targets, bundle, target)
            asset_paths.insert(paths, bundle, frame.anchor.index)
        elif directive in (AFTER_DIRECTIVE, BEFORE_DIRECTIVE):
            self._warn_stranded(directive, paths, targets, bundle, target)
            offset = 1 if directive == AFTER_DIRECTIVE else 0
            target_index = asset_paths.index_of_first(targets, bundle)
            asset_paths.insert(paths, bundle, target_index + offset)
        elif directive == REMOVE_DIRECTIVE:
            if not paths:
                _logger.warning(
                    "REMOVE directive in bundle %r had no effect: path %r "
                    "resolved to nothing. Either the path is stale (file "
                    "renamed / deleted) and the directive can be dropped, "
                    "or the glob is wrong.",
                    bundle,
                    path_def,
                )
                return
            asset_paths.remove(paths, bundle, strict=not is_wildcard_glob(path_def))
        elif directive == REPLACE_DIRECTIVE:
            self._replace(
                paths, targets, bundle, strict=not is_wildcard_glob(target or "")
            )
        else:
            msg = f"Unexpected directive: {directive!r}"
            raise ValueError(msg)

    def _resolve_targets(
        self, directive: str, target: str | None, path_def: str, bundle: str
    ) -> list[str]:
        """Resolve a target-directive anchor to the path(s) it designates.

        Returns ``[]`` (after warning) when the directive is a no-op -- no
        ``target`` given, or the target resolved to nothing on disk. Whether any
        resolved anchor is actually *present* in the bundle is checked by the
        caller, when it looks the position up: an anchor that resolves to real
        files none of which are in the bundle is a hard error, because
        positioning relative to it is undefined.

        A glob target legitimately designates several files, so all of them are
        returned: ``replace`` must drop every one it matched, not just the first.
        """
        if not target:
            _logger.warning(
                "Asset directive %r in bundle %r has no target — "
                "directive skipped. Path was %r.",
                directive,
                bundle,
                path_def,
            )
            return []
        target_paths = self.resolve(target)
        if not target_paths:
            _logger.warning(
                "Asset directive %r in bundle %r references target %r "
                "that resolved to nothing — directive skipped. Path was %r.",
                directive,
                bundle,
                target,
                path_def,
            )
            return []
        return [resolved[0] for resolved in target_paths]

    def _warn_stranded(
        self,
        directive: str,
        paths: Sequence[ResolvedPath],
        targets: Sequence[str],
        bundle: str,
        target: str | None,
    ) -> None:
        """Report the sources a positioning directive will silently not move.

        ``insert`` skips a path the bundle already holds, so every directive
        built on it -- ``prepend`` as much as ``after``/``before`` -- leaves an
        already-present source exactly where it was while looking like it
        positioned it. Only ``replace`` really moves one.

        ``append`` is deliberately not routed here: re-appending a file another
        addon already contributed is the normal, harmless case (3297 of the
        3708 asset commands declared across this workspace are appends), and
        warning on it would bury the directives that genuinely did nothing.
        """
        stranded = [
            path
            for path, _full_path, _last_modified in paths
            if path in self.paths.memo and path not in targets
        ]
        if stranded:
            _logger.warning(
                "Asset directive %r in bundle %r: source(s) %s are already "
                "present and were NOT repositioned (%s only places new files; "
                "use 'replace' to move an existing one). Target was %r.",
                directive,
                bundle,
                stranded,
                directive,
                target,
            )

    def _replace(
        self,
        paths: Sequence[ResolvedPath],
        targets: list[str],
        bundle: str,
        strict: bool = True,
    ) -> None:
        """Position *paths* at the targets' slot in source order, then drop the
        targets.

        Three subtleties (IRASSET-L1):

        * Already-present sources are pulled out first and re-inserted in source
          order, else ``insert`` would skip them and strand them at their old
          position while the target is removed.
        * A target that is itself among the sources (self-replace, or a glob
          matching it) must SURVIVE.
        * A glob target designates every file it matched, so all of them go —
          replacing three files with one is a replacement, not a reshuffle that
          leaves two behind.

        :param strict: whether every target must be in the bundle; False for a
            wildcarded target, whose matches on disk are a superset of what any
            one bundle holds.
        """
        asset_paths = self.paths
        target_set = set(targets)
        if not paths:
            _logger.debug(
                "REPLACE source resolved to nothing in bundle %s, "
                "target(s) %s removed without replacement",
                bundle,
                targets,
            )
        surviving = {entry[0] for entry in paths if entry[0] in target_set}
        sources = [entry for entry in paths if entry[0] not in target_set]
        present = [entry for entry in sources if entry[0] in asset_paths.memo]
        if present:
            asset_paths.remove(present, bundle)
        target_index = asset_paths.index_of_first(targets, bundle)
        asset_paths.insert(sources, bundle, target_index)
        doomed = [
            ResolvedPath(path, None, None) for path in targets if path not in surviving
        ]
        if doomed:
            asset_paths.remove(doomed, bundle, strict=strict)


def manifest_origin(command: Any, addon: str) -> str:
    """Blame string for a directive declared in an addon's manifest."""
    return f"{command!r} in the manifest of addon {addon!r}"


def record_origin(name: str, record_id: Any, directive: str, path: str) -> str:
    """Blame string for a directive declared as an ``ir.asset`` row.

    Manifest commands have always been attributed to their addon; a record
    raised the same bare ``File(s) ... not found`` with nothing pointing back at
    the row to fix, which for a DB-authored directive is the only handle an
    admin has.
    """
    return (
        f"ir.asset record {name!r} (id {record_id}, directive {directive!r}, "
        f"path {path!r})"
    )
