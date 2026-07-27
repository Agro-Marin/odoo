import os
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from functools import partial
from glob import glob
from logging import getLogger
from pathlib import Path
from stat import S_ISLNK
from typing import Any, NamedTuple, Self
from urllib.parse import urlsplit

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import ValidationError
from odoo.libs.constants import ASSET_EXTENSIONS, EXTERNAL_ASSET, ExternalAsset
from odoo.modules import Manifest
from odoo.tools import misc

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
        self.walked_bundles: set[str] = set()
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


@dataclass(slots=True)
class Resolution:
    """Everything one ``_get_asset_paths`` walk needs, gathered once.

    Replaces the six arguments the traversal used to thread through every
    frame, and gives the per-call caches somewhere to live: the addon roots and
    the symlink-containment answers are filesystem facts that hundreds of path
    definitions re-derive otherwise.

    ``assets_params`` is kept because it is the resolution's identity (website,
    lang): it selects the records in :attr:`bundle_assets` and is what an
    override needs to reach.
    """

    installed: Collection[str]
    assets_params: dict[str, Any] = field(default_factory=dict)
    manifest_assets: dict[str, tuple[tuple[str, Any], ...]] = field(
        default_factory=dict
    )
    bundle_assets: dict[str, list] = field(default_factory=dict)
    fetched_bundles: set[str] = field(default_factory=set)
    paths: AssetPaths = field(default_factory=AssetPaths)
    symlink_memo: dict[tuple[str, str], bool] = field(default_factory=dict)
    _manifests: dict[str, Manifest | None] = field(default_factory=dict)
    _addon_roots: dict[str, tuple[str, str]] = field(default_factory=dict)

    def open_bundle(self, bundle: str, seen: tuple[str, ...] = ()) -> BundleFrame:
        """Start a frame for *bundle*, anchoring its segment at the current end."""
        return BundleFrame(bundle, self.paths.new_anchor(), seen)

    def manifest_for(self, addon: str) -> Manifest | None:
        """Return *addon*'s manifest, remembering that it has none.

        ``Manifest`` memoizes the manifests it finds but not the misses, and a
        miss walks every addons path attempting to open a manifest file. Path
        definitions whose first segment is not a module (``/web/content/...``)
        would pay that walk once per definition.
        """
        try:
            return self._manifests[addon]
        except KeyError:
            manifest = Manifest.for_addon(addon, display_warning=False)
            self._manifests[addon] = manifest
            return manifest

    def addon_roots(self, addon: str, manifest: Manifest) -> tuple[str, str]:
        """Return ``(addon_root, static_dir)``, both absolute and symlink-resolved.

        Resolved once per addon so a path definition can be joined onto the root
        lexically instead of being ``realpath``\\ ed again.
        """
        try:
            return self._addon_roots[addon]
        except KeyError:
            root = str(Path(manifest.path).resolve())
            roots = (root, root + os.sep + "static")
            self._addon_roots[addon] = roots
            return roots


class IrAsset(models.Model):
    """Resolve asset bundle file paths, and store directives that customize bundle contents."""

    _name = "ir.asset"
    _description = "Asset"
    _order = "sequence, id"
    _allow_sudo_commands = False

    name = fields.Char(string="Name", required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        string="Sequence", default=DEFAULT_SEQUENCE, required=True
    )
    bundle = fields.Char(string="Bundle name", required=True, index=True)
    directive = fields.Selection(
        string="Directive",
        selection=[
            (APPEND_DIRECTIVE, "Append"),
            (PREPEND_DIRECTIVE, "Prepend"),
            (AFTER_DIRECTIVE, "After"),
            (BEFORE_DIRECTIVE, "Before"),
            (REMOVE_DIRECTIVE, "Remove"),
            (REPLACE_DIRECTIVE, "Replace"),
            (INCLUDE_DIRECTIVE, "Include"),
        ],
        default=APPEND_DIRECTIVE,
        required=True,
    )
    path = fields.Char(string="Path (or glob pattern)", required=True)
    target = fields.Char(string="Target")

    @api.constrains("bundle")
    def _check_bundle_name(self) -> None:
        """Warn -- not raise -- when a bundle can never be served as a file.

        ``_parse_bundle_name`` splits ``<addon>.<name>.min.js`` and demands
        exactly one dot in what is left, so any other spelling resolves fine
        but 404s when the browser asks for it, and the record looks correct
        the whole time. Every one of the 145 bundles declared across this
        workspace's manifests already conforms.

        A hard constraint would be the natural place for an invariant this
        sharp, except that a bundle reached only through ``include`` is never
        parsed as a filename and is therefore legal -- rare, but not wrong, and
        an existing record spelt that way would start rejecting unrelated edits.
        """
        for asset in self:
            if asset.bundle and asset.bundle.count(".") != 1:
                _logger.warning(
                    "ir.asset %r (id %s) targets bundle %r, which is not of the "
                    "form <addon>.<name>; it can only be reached through an "
                    "'include' directive, never served as an asset file.",
                    asset.name,
                    asset.id,
                    asset.bundle,
                )

    @api.constrains("directive", "target")
    def _check_directive_target(self) -> None:
        for asset in self:
            if asset.directive in DIRECTIVES_WITH_TARGET and not asset.target:
                raise ValidationError(
                    self.env._(
                        "Asset %(name)s: directive '%(directive)s' positions its "
                        "path relative to another one, so a Target is required.",
                        name=asset.name,
                        directive=asset.directive,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        records = super().create(vals_list)
        if records:
            self._invalidate_assets_cache()
        return records

    def write(self, vals: dict[str, Any]) -> bool:
        result = super().write(vals)
        if self and not self._resolution_fields().isdisjoint(vals):
            self._invalidate_assets_cache()
        return result

    @api.model
    def _resolution_fields(self) -> frozenset[str]:
        """Fields a bundle's contents depend on.

        Writing anything else -- ``name`` is the whole of it in base -- cannot
        change what a bundle resolves to, so it must not drop the ``assets``
        cache for the worker; a rename of one record currently costs every
        bundle its cached resolution. Extend this in a subclass that adds a
        field the resolution reads (website's ``website_id`` and ``key``
        arbitrate between competing records), or edits to it stop taking effect
        until something else invalidates.
        """
        return frozenset(
            {"active", "sequence", "bundle", "directive", "path", "target"}
        )

    def unlink(self) -> bool:
        had_records = bool(self)
        result = super().unlink()
        if had_records:
            self._invalidate_assets_cache()
        return result

    def _invalidate_assets_cache(self) -> None:
        """Drop the ``assets`` ormcache now *and* again once the change commits.

        Clearing only before/at the write leaves a window until COMMIT during
        which a concurrent reader repopulates the cache from the pre-change
        rows. That entry then outlives the commit: ``Registry.signal_changes``
        only tells the *other* workers to drop theirs, so this worker keeps
        serving the stale bundle until something else invalidates it. Clearing
        again from a post-commit callback closes the window; the immediate clear
        stays so this transaction still reads its own writes.
        """
        registry = self.env.registry
        postcommit = self.env.cr.postcommit
        if not postcommit.data.get("ir_asset_cache_cleared"):
            postcommit.data["ir_asset_cache_cleared"] = True
            postcommit.add(partial(registry.clear_cache, "assets"))
        registry.clear_cache("assets")

    def _get_asset_params(self) -> dict[str, Any]:
        """Return extra parameters for ``_get_asset_paths``.

        Override to inject context (e.g. website_id). Every value must be
        hashable: it becomes part of the ``assets`` ormcache key.
        """
        return {}

    def _get_asset_bundle_url(
        self,
        filename: str,
        unique: str,
        assets_params: dict[str, Any],
        ignore_params: bool = False,
    ) -> str:
        return f"/web/assets/{unique}/{filename}"

    def _parse_bundle_name(
        self, bundle_name: str, debug_assets: bool
    ) -> tuple[str, bool, str, bool]:
        """Parse a bundle filename into ``(bundle_name, rtl, asset_type, autoprefix)``.

        Strips suffixes right-to-left: ``.css``/``.js`` → ``.min`` (non-debug)
        → ``.autoprefixed`` → ``.rtl``, then validates that exactly one dot
        remains (e.g. ``web.assets_frontend``).
        """
        parts = bundle_name.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Bundle filename {bundle_name!r} has no extension (expected .js or .css)"
            )
        bundle_name, asset_type = parts
        rtl = False
        autoprefix = False
        if not debug_assets:
            bundle_name, _, min_ = bundle_name.rpartition(".")
            if min_ != "min":
                raise ValueError(
                    f"'min' expected in extension in non debug mode, got {min_!r}"
                )
        if asset_type == "css":
            if bundle_name.endswith(".autoprefixed"):
                bundle_name = bundle_name.removesuffix(".autoprefixed")
                autoprefix = True
            if bundle_name.endswith(".rtl"):
                bundle_name = bundle_name.removesuffix(".rtl")
                rtl = True
        elif asset_type != "js":
            msg = "Only js and css assets bundle are supported for now"
            raise ValueError(msg)
        if bundle_name.count(".") != 1:
            raise ValueError(
                f"{bundle_name} is not a valid bundle name, should have two parts"
            )
        return bundle_name, rtl, asset_type, autoprefix

    @tools.conditional(
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "bundle", "tuple(sorted(assets_params.items()))", cache="assets"
        ),
    )
    def _get_asset_paths(
        self, bundle: str, assets_params: dict[str, Any]
    ) -> tuple[AssetEntry, ...]:
        """Fetch all asset file paths from addons matching a bundle.

        Loading order: (1) 'ir.asset' records with sequence < 16; (2) the
        addons' manifest declarations, applied in dependency order; (3) the
        remaining 'ir.asset' records.

        Both sources are indexed by bundle up front — see
        :meth:`_get_manifest_assets` and :meth:`_fetch_bundle_assets` — since
        re-scanning either source once per walked bundle made resolution cost
        scale with the depth of the include graph.

        :param assets_params: parameters needed by overrides, mainly website_id
        :returns: tuple of ``AssetEntry``. Immutable because the ormcache hands
            the very same object to every subsequent caller.
        """
        addons = self._get_active_addons_list(**assets_params)
        resolution = Resolution(
            installed=self._get_installed_addons_list(),
            assets_params=assets_params,
            manifest_assets=self._get_manifest_assets(tuple(sorted(addons))),
        )
        self._fetch_bundle_assets(
            resolution, self._included_bundles(bundle, resolution.manifest_assets)
        )
        self._fill_asset_paths(bundle, resolution, ())
        return tuple(resolution.paths.list)

    @api.model
    @tools.ormcache("addons")
    def _get_manifest_assets(
        self, addons: tuple[str, ...]
    ) -> dict[str, tuple[tuple[str, Any], ...]]:
        """Index the manifest ``assets`` declarations of *addons* by bundle name.

        Values are ``(addon, command)`` pairs in the topological addon order the
        directives must be applied in.

        Building this index once — rather than rescanning every manifest for
        each bundle walked — is what keeps resolution independent of the number
        of installed addons: ``Manifest.__getitem__`` deep-copies the value it
        returns, so a per-bundle scan deep-copies every addon's whole asset
        declaration once per bundle.
        """
        by_bundle: dict[str, list[tuple[str, Any]]] = {}
        for addon in self._topological_sort(addons):
            manifest = Manifest.for_addon(addon)
            if manifest is None:
                continue
            for bundle, commands in manifest["assets"].items():
                by_bundle.setdefault(bundle, []).extend(
                    (addon, command) for command in commands
                )
        return {bundle: tuple(commands) for bundle, commands in by_bundle.items()}

    def _fill_asset_paths(
        self, bundle: str, resolution: Resolution, seen: tuple[str, ...]
    ) -> None:
        """Apply *bundle*'s directives to ``resolution.paths``.

        See ``_get_asset_paths`` for the three-phase loading order.

        :param seen: the chain of bundles that included this one, so a cycle is
            reported as the path that closes it rather than as a
            ``RecursionError``
        """
        if bundle in seen:
            raise ValueError(
                f"Circular assets bundle declaration: {' > '.join([*seen, bundle])}"
            )

        asset_paths = resolution.paths
        if bundle in asset_paths.walked_bundles:
            _logger.debug(
                "Bundle %r already walked in this traversal; skipping re-include.",
                bundle,
            )
            return
        asset_paths.walked_bundles.add(bundle)

        frame = resolution.open_bundle(bundle, seen)

        self._fetch_bundle_assets(resolution, (bundle,))
        early_assets, late_assets = [], []
        for asset in resolution.bundle_assets.get(bundle, ()):
            bucket = early_assets if asset.sequence < DEFAULT_SEQUENCE else late_assets
            bucket.append(asset)

        for asset in early_assets:
            self._process_record(asset, frame, resolution)

        for addon, command in resolution.manifest_assets.get(bundle, ()):
            try:
                directive, target, path_def = self._process_command(command)
                self._process_path(frame, resolution, directive, target, path_def)
            except AssetDirectiveError:
                raise
            except ValueError as exc:
                raise AssetDirectiveError(
                    f"{exc} — raised by {command!r}, declared for bundle "
                    f"{bundle!r} in the manifest of addon {addon!r}"
                ) from exc

        for asset in late_assets:
            self._process_record(asset, frame, resolution)

        asset_paths.release_anchor(frame.anchor)

    def _process_record(
        self, asset: Self, frame: BundleFrame, resolution: Resolution
    ) -> None:
        """Apply one ``ir.asset`` record's directive, naming it if it fails.

        Manifest commands have always been attributed to their addon; a record
        raised the same bare ``File(s) ... not found`` with nothing pointing back
        at the row to fix, which for a DB-authored directive is the only handle
        an admin has.
        """
        try:
            self._process_path(
                frame, resolution, asset.directive, asset.target, asset.path
            )
        except AssetDirectiveError:
            raise
        except ValueError as exc:
            raise AssetDirectiveError(
                f"{exc} — raised by ir.asset record {asset.name!r} (id {asset.id}, "
                f"directive {asset.directive!r}, path {asset.path!r}), declared "
                f"for bundle {frame.bundle!r}"
            ) from exc

    def _process_path(
        self,
        frame: BundleFrame,
        resolution: Resolution,
        directive: str,
        target: str | None,
        path_def: str,
    ) -> None:
        """Apply a single directive to ``resolution.paths``.

        :param frame: the bundle being walked and its ``prepend`` anchor
        :param directive: one of the ``*_DIRECTIVE`` constants
        :param target: target path for positional directives, or None
        :param path_def: source path (or glob, or bundle name for include)
        """
        bundle = frame.bundle
        if directive == INCLUDE_DIRECTIVE:
            self._fill_asset_paths(path_def, resolution, (*frame.seen, bundle))
            return

        asset_paths = resolution.paths
        paths = self._get_paths(path_def, resolution)

        targets: list[str] = []
        if directive in DIRECTIVES_WITH_TARGET:
            targets = self._resolve_target_paths(
                directive, target, path_def, bundle, resolution
            )
            if not targets:
                return

        if directive == APPEND_DIRECTIVE:
            asset_paths.append(paths, bundle)
        elif directive == PREPEND_DIRECTIVE:
            asset_paths.insert(paths, bundle, frame.anchor.index)
        elif directive in (AFTER_DIRECTIVE, BEFORE_DIRECTIVE):
            stranded = [
                path
                for path, _full_path, _last_modified in paths
                if path in asset_paths.memo and path not in targets
            ]
            if stranded:
                _logger.warning(
                    "Asset directive %r in bundle %r: source(s) %s are already "
                    "present and were NOT repositioned (after/before only place "
                    "new files; use 'replace' to move an existing one). "
                    "Target was %r.",
                    directive,
                    bundle,
                    stranded,
                    target,
                )
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
            self._apply_replace(
                asset_paths,
                paths,
                targets,
                bundle,
                strict=not is_wildcard_glob(target or ""),
            )
        else:
            msg = f"Unexpected directive: {directive!r}"
            raise ValueError(msg)

    def _resolve_target_paths(
        self,
        directive: str,
        target: str | None,
        path_def: str,
        bundle: str,
        resolution: Resolution,
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
        target_paths = self._get_paths(target, resolution)
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

    def _apply_replace(
        self,
        asset_paths: AssetPaths,
        paths: Sequence[ResolvedPath],
        targets: list[str],
        bundle: str,
        strict: bool = True,
    ) -> None:
        """Apply a REPLACE: position *paths* at the targets' slot in source
        order, then drop the targets.

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
        doomed = [(path, None, None) for path in targets if path not in surviving]
        if doomed:
            asset_paths.remove(doomed, bundle, strict=strict)

    def _get_related_assets(self, domain: list, **kwargs: Any) -> Self:
        """Return assets matching *domain*, regardless of active state.

        Override to widen or narrow the *search* (e.g. a website's domain).
        Choosing between records that compete for the same slot belongs in
        :meth:`_filter_bundle_assets`, which is applied per bundle. The caller
        filters on ``active`` afterward.
        """
        return (
            self.with_context(active_test=False)
            .sudo()
            .search(domain, order="sequence, id")
        )

    def _filter_bundle_assets(self, assets: Self, **kwargs: Any) -> Self:
        """Reduce *assets* -- one bundle's records -- to the ones that apply.

        Called once per bundle so that "most specific record wins" arbitration
        (website's generic-vs-specific ``key`` matching) compares records that
        actually compete. Doing it on a batch spanning several bundles instead
        lets a specific record in one bundle suppress the generic record of
        another: reproduced with a website COW write that also moves the record
        to a different bundle, which drops the generic one entirely.
        """
        return assets

    def _fetch_bundle_assets(
        self, resolution: Resolution, bundles: Collection[str]
    ) -> None:
        """Index the active ``ir.asset`` records of *bundles* into *resolution*.

        A resolution walks a bundle plus every bundle it includes -- 13 of them
        for ``web.assets_backend`` -- and issued one search per walked bundle,
        re-selecting from the same table each time. Fetching the *whole* table
        once instead removes those round-trips but makes the cost grow with
        rows a bundle will never use: measured on this workspace it wins below
        ~1000 ``ir.asset`` rows and loses 2x at 20 000, which a multi-website
        install with per-website copies can reach. So the set is bounded
        up front by :meth:`_included_bundles` and fetched in one query, with
        this same method called again for any bundle only an ``ir.asset``
        ``include`` record reveals.

        One query, but :meth:`_filter_bundle_assets` still arbitrates per
        bundle, so batching cannot make one bundle's records suppress another's.

        Records keep the ``sequence, id`` order :meth:`_get_related_assets`
        returns them in, which is what the early/late split relies on.
        """
        missing = [b for b in bundles if b not in resolution.fetched_bundles]
        if not missing:
            return
        resolution.fetched_bundles.update(missing)
        assets = self._get_related_assets(
            [("bundle", "in", missing)], **resolution.assets_params
        )
        ids_by_bundle: dict[str, list[int]] = {}
        for asset in assets:
            ids_by_bundle.setdefault(asset.bundle, []).append(asset.id)
        for bundle, ids in ids_by_bundle.items():
            applicable = self._filter_bundle_assets(
                assets.browse(ids), **resolution.assets_params
            ).filtered("active")
            if applicable:
                resolution.bundle_assets[bundle] = list(applicable)

    def _included_bundles(
        self, bundle: str, manifest_assets: dict[str, tuple[tuple[str, Any], ...]]
    ) -> set[str]:
        """Bundles reachable from *bundle* through manifest ``include`` commands.

        Malformed commands are ignored here on purpose: this is a prefetch hint,
        and reporting a bad command is :meth:`_process_command`'s job, where the
        error can name the addon that declared it.
        """
        closure: set[str] = set()
        pending = [bundle]
        while pending:
            current = pending.pop()
            if current in closure:
                continue
            closure.add(current)
            for _addon, command in manifest_assets.get(current, ()):
                if (
                    isinstance(command, list | tuple)
                    and len(command) == 2
                    and command[0] == INCLUDE_DIRECTIVE
                ):
                    pending.append(command[1])
        return closure

    def _get_related_bundle(self, target_path_def: str, root_bundle: str) -> str:
        """Return the first bundle directly defining *target_path_def*.

        Useful when generating an 'ir.asset' record to override a specific
        asset.

        :param root_bundle: bundle from which to start the search
        :returns: the first matching bundle, or *root_bundle* as fallback
        """
        resolution = Resolution(installed=self._get_installed_addons_list())
        paths = self._get_paths(target_path_def, resolution)
        if not paths:
            return root_bundle
        target_path = paths[0][0]
        assets_params = self._get_asset_params()
        asset_paths = self._get_asset_paths(root_bundle, assets_params)

        for entry in asset_paths:
            if entry.path == target_path:
                return entry.bundle

        return root_bundle

    def _get_active_addons_list(self, **kwargs: Any) -> Collection[str]:
        """Return the active addons for asset resolution.

        Override to filter modules (e.g. discard inactive themes per website).
        """
        return self._get_installed_addons_list()

    @api.model
    @tools.ormcache("addons_tuple")
    def _topological_sort(self, addons_tuple: tuple[str, ...]) -> tuple[str, ...]:
        """Return addon names sorted by ir.module.module ordering.

        Sorts by application (desc), sequence, name, then topologically to
        respect dependency order.

        Immutable: the ormcache hands the same object to every caller.
        """
        IrModule = self.env["ir.module.module"]

        def mapper(addon):
            manif = Manifest.for_addon(addon) or {}
            from_terp = IrModule.get_values_from_terp(manif)
            from_terp["name"] = addon
            from_terp["depends"] = manif.get("depends") or ["base"]
            return from_terp

        sorted_manifs = sorted(
            map(mapper, addons_tuple),
            key=lambda m: (not m["application"], int(m["sequence"]), m["name"]),
        )

        return tuple(
            misc.topological_sort(
                {m["name"]: tuple(m["depends"]) for m in sorted_manifs}
            )
        )

    @api.model
    def _get_installed_addons_list(self) -> frozenset[str]:
        """Return the set of all installed addon names.

        Deliberately *not* ormcached. It reads ``registry._init_modules``, a set
        the module loader fills in as it goes, and an ormcache with no key would
        freeze whatever prefix of it happened to be loaded when the first caller
        asked — for the life of the registry, since ``Registry.new`` hands the
        one being loaded straight over to the workers and nothing on that path
        clears the cache. Measured on this workspace the cache saved 0.7 us on
        each of the two calls a resolution makes, against a 43 ms resolution.

        Returns a frozenset so a caller cannot mutate the answer either.
        """
        return frozenset(
            self.env.registry._init_modules.union(tools.config["server_wide_modules"])
        )

    def _get_paths(self, path_def: str, resolution: Resolution) -> list[ResolvedPath]:
        """Resolve *path_def* to a list of ``ResolvedPath`` tuples.

        Globs can only occur inside the ``static/`` directory of an installed
        addon. The ``full_path`` field distinguishes the resolution kind: a
        filesystem path (static file), the ``EXTERNAL_ASSET`` sentinel
        (http:// or /web/content), or ``None`` (attachment fallback).

        Containment is decided lexically, against the addon root
        :meth:`Resolution.addon_static_root` already resolved: ``..`` is
        collapsed without consulting the filesystem, and a symlink met on the
        way is caught where a wildcard could also land on one, in
        :func:`_glob_static_file`. Resolving the whole path here instead cost a
        second ``realpath`` per definition and made a literal path through a
        symlink and a glob expanding onto the same symlink take different
        branches.

        :param path_def: glob or URL to resolve
        :param resolution: the current walk, for its installed addons and its
            filesystem caches
        """
        path_def = fs2web(path_def)
        path_parts = [part for part in path_def.split("/") if part]
        if not path_parts:
            _logger.warning("IrAsset: empty path definition")
            return []
        if not can_aggregate(path_def):
            return [ResolvedPath(path_def, EXTERNAL_ASSET, -1)]

        paths = None
        addon = path_parts[0]
        addon_manifest = resolution.manifest_for(addon)

        safe_path = False
        if addon_manifest:
            if addon not in resolution.installed:
                _logger.debug(
                    "Skipping asset %s: addon %s not loaded yet",
                    path_def,
                    addon,
                )
                return []
            addon_root, static_dir = resolution.addon_roots(addon, addon_manifest)
            full_path = os.path.normpath("/".join([addon_root, *path_parts[1:]]))
            if full_path == static_dir or full_path.startswith(static_dir + os.sep):
                paths_with_timestamps = _glob_static_file(
                    full_path, static_dir, resolution.symlink_memo
                )
                root_len = len(addon_root) + 1
                paths = [
                    ResolvedPath(
                        f"/{addon}/{fs2web(absolute_path[root_len:])}",
                        absolute_path,
                        timestamp,
                    )
                    for absolute_path, timestamp in paths_with_timestamps
                ]
                safe_path = True

        if not paths and not is_wildcard_glob(path_def):
            if addon_manifest and not safe_path:
                _logger.warning(
                    "IrAsset: path %r resolves outside the static/ directory of "
                    "addon %r; treating it as an attachment URL. This is almost "
                    "certainly a stale or escaping path.",
                    path_def,
                    addon,
                )
            elif addon_manifest:
                if not (
                    self.env["ir.attachment"]
                    .sudo()
                    .search_count([("url", "in", (path_def, f"/{path_def}"))], limit=1)
                ):
                    _logger.warning(
                        "IrAsset: path %r matches no bundleable file in the "
                        "static/ directory of addon %r (missing file or "
                        "non-asset extension) and no attachment claims that "
                        "URL; treating it as an attachment URL. This is "
                        "almost certainly a typo in the path.",
                        path_def,
                        addon,
                    )
            paths = [ResolvedPath(path_def, None, None)]

        if not paths:
            msg = f'IrAsset: the path "{path_def}" did not resolve to anything.'
            if not safe_path:
                msg += " It may be due to security reasons."
            _logger.warning(msg)
            return []
        return paths

    def _process_command(self, command: str | list) -> tuple[str, str | None, str]:
        """Parse a manifest asset command into ``(directive, target, path_def)``.

        Accepts a plain string (implicit append) or a list whose first element
        is the directive name.
        """
        if isinstance(command, str):
            return APPEND_DIRECTIVE, None, command
        try:
            if command[0] in DIRECTIVES_WITH_TARGET:
                directive, target, path_def = command
            else:
                directive, path_def = command
                target = None
        except (ValueError, IndexError, TypeError, KeyError) as exc:
            raise ValueError(f"Malformed asset command: {command!r}") from exc
        return directive, target, path_def
