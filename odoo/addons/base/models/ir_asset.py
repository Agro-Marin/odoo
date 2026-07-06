import os
from collections.abc import Collection
from glob import glob
from logging import getLogger
from pathlib import Path
from typing import Any, NamedTuple, Self
from urllib.parse import urlsplit

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.libs.constants import ASSET_EXTENSIONS, EXTERNAL_ASSET
from odoo.modules import Manifest
from odoo.tools import misc

_logger = getLogger(__name__)

DEFAULT_SEQUENCE = 16

# Directives are stored in variables for ease of use and syntax checks.
APPEND_DIRECTIVE = "append"
PREPEND_DIRECTIVE = "prepend"
AFTER_DIRECTIVE = "after"
BEFORE_DIRECTIVE = "before"
REMOVE_DIRECTIVE = "remove"
REPLACE_DIRECTIVE = "replace"
INCLUDE_DIRECTIVE = "include"
# Those are the directives used with a 'target' argument/field. Keep in sync
# with the ``directive`` Selection field and the dispatch in ``_process_path``.
DIRECTIVES_WITH_TARGET = {AFTER_DIRECTIVE, BEFORE_DIRECTIVE, REPLACE_DIRECTIVE}


class ResolvedPath(NamedTuple):
    """A single path produced by :meth:`IrAsset._get_paths`, not yet bound to
    a bundle.

    ``full_path`` encodes the *kind* of the resolution:

    * canonical filesystem path -> a static file on disk;
    * :data:`EXTERNAL_ASSET` sentinel -> an external URL (served as-is);
    * ``None`` -> an attachment URL (resolved later against ir.attachment).

    It stays a plain tuple at runtime, so existing positional unpacking
    ``(path, full_path, last_modified)`` keeps working.
    """

    path: str
    full_path: Any
    last_modified: Any


class AssetEntry(NamedTuple):
    """One resolved asset bound to the bundle that contributed it.

    Positionally identical to the legacy 4-tuple
    ``(path, full_path, bundle, last_modified)`` that consumers unpack, so it
    is a drop-in replacement while giving the fields names.
    """

    path: str
    full_path: Any
    bundle: str
    last_modified: Any

    @property
    def is_external(self) -> bool:
        """True for an external URL served individually (not bundled)."""
        return self.full_path is EXTERNAL_ASSET


def fs2web(path: str) -> str:
    """Converts a file system path to a web path."""
    if os.sep == "/":
        return path
    return "/".join(path.split(os.sep))  # noqa: PTH206


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
    """Determine whether *path* is a wildcarded glob.

    Examples: ``/web/file[14].*`` (glob) vs ``/web/myfile.scss`` (plain).
    """
    return any(char in path for char in "*?[]")


def _glob_static_file(pattern: str) -> list[tuple[str, float]]:
    """Glob *pattern* for static files and return ``(path, mtime)`` pairs.

    Only files whose extension is in ``ASSET_EXTENSIONS`` are included.
    Results are sorted by path for deterministic bundle ordering.
    Files deleted between ``glob()`` and ``stat()`` (e.g. during hot-reload)
    are silently skipped.
    """
    result: list[tuple[str, float]] = []
    for file in glob(pattern, recursive=True):  # noqa: PTH207
        if file.rsplit(".", 1)[-1] not in ASSET_EXTENSIONS:
            continue
        try:
            mtime = Path(file).stat().st_mtime
        except FileNotFoundError:
            continue
        result.append((file, mtime))
    result.sort()
    return result


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
    bundle = fields.Char(string="Bundle name", required=True)
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
    )
    path = fields.Char(string="Path (or glob pattern)", required=True)
    target = fields.Char(string="Target")

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        if vals_list:
            self.env.registry.clear_cache("assets")
        return super().create(vals_list)

    def write(self, vals: dict[str, Any]) -> bool:
        if self:
            self.env.registry.clear_cache("assets")
        return super().write(vals)

    def unlink(self) -> bool:
        if self:
            self.env.registry.clear_cache("assets")
        return super().unlink()

    def _get_asset_params(self) -> dict[str, Any]:
        """Returns extra parameters for ``_get_asset_paths``.

        Override to inject context (e.g. website_id) into the ORM cache key.
        Every value must be hashable: it becomes part of the ``assets`` ormcache
        key (see ``_get_asset_paths``).
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
        """Parses a bundle filename into its components.

        Strips suffixes right-to-left: ``.css``/``.js`` → ``.min`` (non-debug)
        → ``.autoprefixed`` → ``.rtl``, then validates that exactly one dot
        remains (e.g. ``web.assets_frontend``).

        :returns: ``(bundle_name, rtl, asset_type, autoprefix)``
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
            bundle_name, min_ = bundle_name.rsplit(".", 1)
            if min_ != "min":
                msg = "'min' expected in extension in non debug mode"
                raise ValueError(msg)
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
    ) -> list[AssetEntry]:
        """Fetches all asset file paths from addons matching a bundle.

        The returned list is composed of ``AssetEntry`` tuples
        ``(path, full_path, bundle, last_modified)``.
        Asset loading is performed as follows:

        1. All 'ir.asset' records matching the given bundle and with a sequence
           strictly less than 16 are applied.

        2. The manifests of the given addons are checked for assets declaration
           for the given bundle. If any, they are read sequentially and their
           operations are applied to the current list.

        3. After all manifests have been parsed, the remaining 'ir.asset'
           records matching the bundle are also applied to the current list.

        :param bundle: name of the bundle from which to fetch the file paths
        :param assets_params: parameters needed by overrides, mainly website_id
            (see ``_get_asset_params``)
        :returns: list of ``AssetEntry`` (path, full_path, bundle, last_modified)
        """
        installed = self._get_installed_addons_list()
        addons = self._get_active_addons_list(**assets_params)
        asset_paths = AssetPaths()
        # ``addons`` is a set, whose iteration order is process-dependent (string
        # hash randomization). Sort before building the tuple so the
        # ``_topological_sort`` @ormcache key is canonical across workers and
        # restarts (the result is order-independent regardless; this only
        # prevents cache fragmentation -- IRASSET-P1).
        addons = self._topological_sort(tuple(sorted(addons)))
        self._fill_asset_paths(
            bundle, asset_paths, [], addons, installed, **assets_params
        )
        return asset_paths.list

    def _fill_asset_paths(
        self,
        bundle: str,
        asset_paths: AssetPaths,
        seen: list[str],
        addons: list[str],
        installed: Collection[str],
        **assets_params: Any,
    ) -> None:
        """Fills *asset_paths* by applying the operations found in manifests.

        See ``_get_asset_paths`` for the three-phase loading order.

        :param bundle: name of the bundle from which to fetch the file paths
        :param addons: topologically sorted addon names
        :param asset_paths: the AssetPaths instance to fill
        :param seen: bundles already visited (circularity guard)
        :param assets_params: extra context forwarded to overrides
            (e.g. website_id)
        """
        if bundle in seen:
            raise ValueError(
                f"Circular assets bundle declaration: {' > '.join(seen + [bundle])}"
            )

        # A sub-bundle can be legitimately included several times in the same
        # traversal (e.g. ``web._assets_primary_variables`` is included both
        # directly by most top-level bundles AND via ``web._assets_helpers``).
        # The first walk fully determines its contribution: directives are
        # deterministic within a traversal, so on a re-walk append/insert are
        # memo-deduplicated no-ops, after/before log spurious "already
        # present" warnings, and remove/replace would re-apply against the
        # already-mutated state (up to a hard ValueError for remove). Skip
        # re-walks entirely. The circularity check above stays first so real
        # cycles keep raising instead of being masked as re-includes.
        if bundle in asset_paths.walked_bundles:
            _logger.debug(
                "Bundle %r already walked in this traversal; skipping re-include.",
                bundle,
            )
            return
        asset_paths.walked_bundles.add(bundle)

        # this index is used for prepending: files are inserted at the beginning
        # of the CURRENT bundle.
        bundle_start_index = len(asset_paths.list)

        assets = self._get_related_assets(
            [("bundle", "=", bundle)], **assets_params
        ).filtered("active")
        # Partition once (the recordset is already ordered by ``sequence, id``)
        # into the pre-manifest (sequence < 16) and post-manifest phases.
        early_assets, late_assets = [], []
        for asset in assets:
            bucket = early_assets if asset.sequence < DEFAULT_SEQUENCE else late_assets
            bucket.append(asset)

        # 1. Process the first sequence of 'ir.asset' records
        for asset in early_assets:
            self._process_path(
                bundle,
                asset.directive,
                asset.target,
                asset.path,
                asset_paths,
                seen,
                addons,
                installed,
                bundle_start_index,
                **assets_params,
            )

        # 2. Process all addons' manifests.
        for addon in addons:
            manifest = Manifest.for_addon(addon)
            if manifest is None:
                continue
            for command in manifest["assets"].get(bundle, ()):
                directive, target, path_def = self._process_command(command)
                self._process_path(
                    bundle,
                    directive,
                    target,
                    path_def,
                    asset_paths,
                    seen,
                    addons,
                    installed,
                    bundle_start_index,
                    **assets_params,
                )

        # 3. Process the rest of 'ir.asset' records
        for asset in late_assets:
            self._process_path(
                bundle,
                asset.directive,
                asset.target,
                asset.path,
                asset_paths,
                seen,
                addons,
                installed,
                bundle_start_index,
                **assets_params,
            )

    def _process_path(
        self,
        bundle: str,
        directive: str,
        target: str | None,
        path_def: str,
        asset_paths: AssetPaths,
        seen: list[str],
        addons: list[str],
        installed: Collection[str],
        bundle_start_index: int,
        **assets_params: Any,
    ) -> None:
        """Applies a single directive to *asset_paths*.

        :param directive: one of the ``*_DIRECTIVE`` constants
        :param target: target path for positional directives, or None
        :param path_def: source path (or glob, or bundle name for include)
        """
        if directive == INCLUDE_DIRECTIVE:
            self._fill_asset_paths(
                path_def,
                asset_paths,
                seen + [bundle],
                addons,
                installed,
                **assets_params,
            )
            return

        # ``_get_paths`` already handles external URLs and ``/web/content``
        # (returning an EXTERNAL_ASSET tuple), so it is the single resolution
        # entry point -- no need to pre-check ``can_aggregate`` here.
        paths = self._get_paths(path_def, installed)

        # Resolve the anchor for target directives (after/before/replace).
        target_path = target_index = None
        if directive in DIRECTIVES_WITH_TARGET:
            resolved = self._resolve_target(
                directive, target, path_def, bundle, installed, asset_paths
            )
            if resolved is None:
                return  # a no-op was logged; nothing to apply
            target_path, target_index = resolved

        if directive == APPEND_DIRECTIVE:
            asset_paths.append(paths, bundle)
        elif directive == PREPEND_DIRECTIVE:
            asset_paths.insert(paths, bundle, bundle_start_index)
        elif directive in (AFTER_DIRECTIVE, BEFORE_DIRECTIVE):
            # ``insert`` skips sources already in the bundle, so an
            # after/before that names an already-present file is a silent
            # no-op: the file is NOT moved. (``replace`` is the only directive
            # that repositions an existing source -- see ``_apply_replace``.)
            # Warn so an ineffective reorder is visible; exclude the anchor
            # itself, which is legitimately present.
            stranded = [
                path
                for path, _full_path, _last_modified in paths
                if path in asset_paths.memo and path != target_path
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
            asset_paths.insert(paths, bundle, target_index + offset)
        elif directive == REMOVE_DIRECTIVE:
            if not paths:
                # ``("remove", "moved_or_deleted_file.js")`` — the path no
                # longer resolves to anything on disk, so the remove is a
                # silent no-op.  A ``remove`` whose target no longer exists is
                # dead weight that hides whether the bundle still needs the
                # directive, so we warn rather than fail.
                _logger.warning(
                    "REMOVE directive in bundle %r had no effect: path %r "
                    "resolved to nothing. Either the path is stale (file "
                    "renamed / deleted) and the directive can be dropped, "
                    "or the glob is wrong.",
                    bundle,
                    path_def,
                )
                return
            asset_paths.remove(paths, bundle)
        elif directive == REPLACE_DIRECTIVE:
            self._apply_replace(asset_paths, paths, target_path, bundle)
        else:
            msg = f"Unexpected directive: {directive!r}"
            raise ValueError(msg)

    def _resolve_target(
        self,
        directive: str,
        target: str | None,
        path_def: str,
        bundle: str,
        installed: Collection[str],
        asset_paths: AssetPaths,
    ) -> tuple[str, int] | None:
        """Resolve a target-directive anchor to ``(target_path, index)``.

        Returns ``None`` (after logging a warning) when the directive is a
        silent no-op -- either no ``target`` was given, or the target resolved
        to nothing on disk (renamed / removed since the directive was written).

        :raises ValueError: via ``AssetPaths.index`` when the anchor resolves to
            a real file that is simply *not present* in this bundle. Positioning
            relative to an absent anchor is undefined, so this is a hard error
            (upstream-faithful contract, pinned by ir.asset audit tests).
        """
        if not target:
            # Manifest tuple was ``("after", "")`` or ``("after", None, ...)``.
            # We can never resolve a target index, so the directive is a
            # silent no-op.  Surface it with bundle+directive context so the
            # operator does not have to grep the manifest by hand.
            _logger.warning(
                "Asset directive %r in bundle %r has no target — "
                "directive skipped. Path was %r.",
                directive,
                bundle,
                path_def,
            )
            return None
        target_paths = self._get_paths(target, installed)
        if not target_paths:
            # The anchor file (the ``target`` of ``after`` / ``before`` /
            # ``replace``) resolved to nothing — typically because it was
            # renamed or removed since the directive was written.  Without this
            # warning the directive would become a silent no-op, so we log it.
            _logger.warning(
                "Asset directive %r in bundle %r references target %r "
                "that resolved to nothing — directive skipped. Path was %r.",
                directive,
                bundle,
                target,
                path_def,
            )
            return None
        target_path = target_paths[0][0]
        return target_path, asset_paths.index(target_path, bundle)

    def _apply_replace(
        self,
        asset_paths: AssetPaths,
        paths: list,
        target_path: str,
        bundle: str,
    ) -> None:
        """Apply a REPLACE: position *paths* at *target_path*'s slot, preserving
        source order, then drop the target.

        Two subtleties (IRASSET-L1):

        * A source already present in the bundle would be a no-op for
          ``insert`` and get stranded while the target is removed -- so
          already-present sources are pulled out first and re-inserted in
          source order rather than dropped.
        * If the target is itself among the sources (a self-replace, or a glob
          whose matches include the target), the target must SURVIVE.
        """
        if not paths:
            # Documented "delete the target" idiom: empty source.
            _logger.debug(
                "REPLACE source resolved to nothing in bundle %s, "
                "target %s removed without replacement",
                bundle,
                target_path,
            )
        target_in_source = any(p[0] == target_path for p in paths)
        # Sources in their original order, excluding the target itself.
        sources = [p for p in paths if p[0] != target_path]
        # Pull out already-present sources so ``insert`` (which skips paths
        # already in ``memo``) re-adds them in source order instead of leaving
        # them stranded at their old position.
        present = [p for p in sources if p[0] in asset_paths.memo]
        if present:
            asset_paths.remove(present, bundle)
        # Re-derive the index AFTER the removals above -- they may have shifted
        # earlier elements. The target itself is never in ``present``, so it is
        # still there to anchor on.
        target_index = asset_paths.index(target_path, bundle)
        asset_paths.insert(sources, bundle, target_index)
        if not target_in_source:
            asset_paths.remove([(target_path, None, None)], bundle)

    def _get_related_assets(self, domain: list, **kwargs: Any) -> Self:
        """Returns assets matching *domain*, regardless of active state.

        Override to filter results (e.g. website-specific deduplication).
        The caller is responsible for filtering on ``active`` afterward.
        """
        # active_test is needed to disable some assets through filter_duplicate for website
        # they will be filtered on active afterward
        return (
            self.with_context(active_test=False)
            .sudo()
            .search(domain, order="sequence, id")
        )

    def _get_related_bundle(self, target_path_def: str, root_bundle: str) -> str:
        """Returns the first bundle directly defining *target_path_def*.

        Useful when generating an 'ir.asset' record to override a specific
        asset: target the first bundle that declares the path.

        :param target_path_def: path to match.
        :param root_bundle: bundle from which to initiate the search.
        :returns: the first matching bundle, or *root_bundle* as fallback.
        """
        installed = self._get_installed_addons_list()
        paths = self._get_paths(target_path_def, installed)
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
        """Returns the active addons for asset resolution.

        Override to filter modules (e.g. discard inactive themes per website).
        """
        return self._get_installed_addons_list()

    @api.model
    @tools.ormcache("addons_tuple")
    def _topological_sort(self, addons_tuple: tuple[str, ...]) -> list[str]:
        """Returns addon names sorted according to ir.module.module ordering.

        First sorts by application (desc), sequence, name, then applies
        topological sorting to respect dependency order.
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

        return misc.topological_sort(
            {m["name"]: tuple(m["depends"]) for m in sorted_manifs}
        )

    @api.model
    @tools.ormcache()
    def _get_installed_addons_list(self) -> set[str]:
        """Returns the set of all installed addon names."""
        return self.env.registry._init_modules.union(
            tools.config["server_wide_modules"]
        )

    def _get_paths(
        self, path_def: str, installed: Collection[str]
    ) -> list[ResolvedPath]:
        """Resolves *path_def* to a list of ``ResolvedPath`` tuples.

        Globs can only occur inside the ``static/`` directory of an installed addon.

        Depending on the kind of path, the tuple contents differ:

        * Static file:
          ``('/base/static/file.js', '/home/.../base/static/file.js', 643636800.0)``
        * External URL (http://, /web/content):
          ``('http://example.com/lib.js', EXTERNAL_ASSET, -1)``
        * Attachment / non-wildcard fallback:
          ``('/_custom/web.asset_frontend', None, None)``

        :param path_def: glob or URL to resolve
        :param installed: set of installed addon names
        """
        paths = None
        path_def = fs2web(path_def)
        path_parts = [part for part in path_def.split("/") if part]
        if not path_parts:
            _logger.warning("IrAsset: empty path definition")
            return []
        addon = path_parts[0]
        addon_manifest = Manifest.for_addon(addon, display_warning=False)

        safe_path = False
        if addon_manifest:
            if addon not in installed:
                # During module loading, tests may run before all modules are
                # in _init_modules.  Skip assets from not-yet-loaded addons
                # instead of crashing; once fully loaded this is unreachable
                # because uninstalled addons have no ir.asset records.
                _logger.debug(
                    "Skipping asset %s: addon %s not loaded yet",
                    path_def,
                    addon,
                )
                return []
            addons_path = addon_manifest.addons_path
            full_path = Path(addons_path, *path_parts).resolve()
            # forbid escape from the current addon
            # "/mymodule/../myothermodule" is forbidden
            static_dir = Path(addon_manifest.path, "static").resolve()
            if full_path.is_relative_to(static_dir):
                paths_with_timestamps = _glob_static_file(str(full_path))
                # ``absolute_path`` is canonicalized (it comes from globbing a
                # ``.resolve()``d ``full_path``), so strip the *resolved*
                # addons_path. Using the raw manifest ``addons_path`` would
                # silently fail to strip when it contains symlinks or ``..``,
                # yielding a malformed web path (IRASSET-M2).
                prefix = str(Path(addons_path).resolve()) + os.sep
                paths = [
                    ResolvedPath(
                        "/" + fs2web(absolute_path.removeprefix(prefix)),
                        absolute_path,
                        timestamp,
                    )
                    for absolute_path, timestamp in paths_with_timestamps
                ]
                safe_path = True

        if not paths and not can_aggregate(path_def):  # http:// or /web/content
            paths = [ResolvedPath(path_def, EXTERNAL_ASSET, -1)]

        if not paths and not is_wildcard_glob(path_def):
            # an attachment url most likely
            if addon_manifest and not safe_path:
                # ``path_def`` names an installed addon but resolves *outside*
                # that addon's ``static/`` dir (e.g. ``/mymod/../other``). It is
                # not globbed (escape guard) and silently degrades to an
                # attachment URL -- almost always a mistake. The empty-glob
                # sibling case already warns below; warn here too so the escape
                # is not the one path that resolves without a trace (IRASSET-C4).
                _logger.warning(
                    "IrAsset: path %r resolves outside the static/ directory of "
                    "addon %r; treating it as an attachment URL. This is almost "
                    "certainly a stale or escaping path.",
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
        """Parses a manifest asset command into ``(directive, target, path_def)``.

        Accepts either a plain string (implicit append) or a list whose first
        element is the directive name.
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
            # Catch every way a non-(str|list) or wrong-arity command can fail
            # to unpack -- a bare int raises TypeError, a dict raises KeyError,
            # wrong length raises ValueError. Re-raise as a ValueError whose
            # *message* (not just __notes__, which str(exc) hides) names the
            # offending command, so the manifest error is never lost.
            raise ValueError(f"Malformed asset command: {command!r}") from exc
        return directive, target, path_def


class AssetPaths:
    """A deduplicated list of asset paths with positional operations.

    Each entry is an ``AssetEntry`` ``(path, full_path, bundle, last_modified)``.
    The ``memo`` set tracks seen paths to enforce uniqueness in O(1).

    Mutating methods accept 3-element source tuples ``(path, full_path,
    last_modified)`` and bind them to *bundle* to build the stored 4-element
    ``AssetEntry``.
    """

    def __init__(self) -> None:
        self.list: list[AssetEntry] = []
        self.memo: set[str] = set()
        # Bundle names already walked in this traversal; lets the filling
        # logic skip duplicate includes of the same sub-bundle (see
        # ``IrAsset._fill_asset_paths``).
        self.walked_bundles: set[str] = set()

    def index(self, path: str, bundle: str) -> int:
        """Returns the index of the given path in the current assets list."""
        if path not in self.memo:
            self._raise_not_found(path, bundle)
        for index, asset in enumerate(self.list):
            if asset.path == path:
                return index
        raise RuntimeError(
            f"Inconsistent asset state: {path!r} in memo but not in list"
        )

    def append(self, paths: list, bundle: str) -> None:
        """Appends the given paths to the current list."""
        for path, full_path, last_modified in paths:
            if path not in self.memo:
                self.list.append(AssetEntry(path, full_path, bundle, last_modified))
                self.memo.add(path)

    def insert(self, paths: list, bundle: str, index: int) -> None:
        """Inserts the given paths to the current list at the given position."""
        to_insert = []
        for path, full_path, last_modified in paths:
            if path not in self.memo:
                to_insert.append(AssetEntry(path, full_path, bundle, last_modified))
                self.memo.add(path)
        self.list[index:index] = to_insert

    def remove(self, paths_to_remove: list, bundle: str) -> None:
        """Removes the given paths from the current list.

        Semantics by how many requested paths are in the bundle:

        * all present -> removed silently;
        * some present, some absent -> the present ones are removed and the
          absent (stale) ones are WARNED about (IRASSET-A3) rather than
          dropped silently;
        * none present -> hard error (positioning/removal relative to a
          resolvable-but-absent path is a contract violation).
        """
        requested = [path for path, _full_path, _last_modified in paths_to_remove]
        present = {path for path in requested if path in self.memo}
        if present:
            absent = [path for path in requested if path not in self.memo]
            if absent:
                _logger.warning(
                    "REMOVE in bundle %r ignored path(s) %s not present in the "
                    "bundle (removed %s). The ignored paths are likely stale "
                    "(renamed/deleted) or an over-matching glob.",
                    bundle,
                    absent,
                    sorted(present),
                )
            self.list[:] = [asset for asset in self.list if asset.path not in present]
            self.memo.difference_update(present)
            return

        if requested:
            self._raise_not_found(requested, bundle)

    def _raise_not_found(self, path: str | list[str], bundle: str) -> None:
        raise ValueError(f"File(s) {path} not found in bundle {bundle}")
