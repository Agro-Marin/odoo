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

APPEND_DIRECTIVE = "append"
PREPEND_DIRECTIVE = "prepend"
AFTER_DIRECTIVE = "after"
BEFORE_DIRECTIVE = "before"
REMOVE_DIRECTIVE = "remove"
REPLACE_DIRECTIVE = "replace"
INCLUDE_DIRECTIVE = "include"
# Directives taking a 'target'. Keep in sync with the ``directive`` Selection
# field and the dispatch in ``_process_path``.
DIRECTIVES_WITH_TARGET = {AFTER_DIRECTIVE, BEFORE_DIRECTIVE, REPLACE_DIRECTIVE}


class ResolvedPath(NamedTuple):
    """A path from :meth:`IrAsset._get_paths`, not yet bound to a bundle.

    ``full_path`` encodes the resolution kind: a filesystem path (static file),
    the :data:`EXTERNAL_ASSET` sentinel (external URL served as-is), or ``None``
    (attachment URL, resolved later against ir.attachment).
    """

    path: str
    full_path: Any
    last_modified: Any


class AssetEntry(NamedTuple):
    """One resolved asset bound to the bundle that contributed it.

    Positionally the 4-tuple ``(path, full_path, bundle, last_modified)`` that
    consumers unpack.
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
    """Convert a filesystem path to a web path."""
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
    """Whether *path* is a wildcarded glob (e.g. ``/web/file[14].*``)."""
    return any(char in path for char in "*?[]")


def _glob_static_file(pattern: str) -> list[tuple[str, float]]:
    """Glob *pattern* for static files, returning sorted ``(path, mtime)`` pairs.

    Only ``ASSET_EXTENSIONS`` files are included; sorted for deterministic
    bundle ordering. Files deleted between ``glob()`` and ``stat()`` (e.g.
    during hot-reload) are skipped.
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
        """Fetch all asset file paths from addons matching a bundle.

        Loading order: (1) 'ir.asset' records with sequence < 16; (2) the
        addons' manifest declarations, applied in dependency order; (3) the
        remaining 'ir.asset' records.

        :param assets_params: parameters needed by overrides, mainly website_id
        :returns: list of ``AssetEntry``
        """
        installed = self._get_installed_addons_list()
        addons = self._get_active_addons_list(**assets_params)
        asset_paths = AssetPaths()
        # Sort the addons set before building the tuple so the
        # ``_topological_sort`` @ormcache key is canonical across workers and
        # restarts (hash-randomized set order would fragment the cache -- the
        # result is order-independent regardless -- IRASSET-P1).
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
        """Fill *asset_paths* by applying the bundle's directives.

        See ``_get_asset_paths`` for the three-phase loading order.

        :param addons: topologically sorted addon names
        :param seen: bundles already visited (circularity guard)
        :param assets_params: extra context forwarded to overrides
        """
        if bundle in seen:
            raise ValueError(
                f"Circular assets bundle declaration: {' > '.join(seen + [bundle])}"
            )

        # A sub-bundle can legitimately be included several times in one
        # traversal (e.g. ``web._assets_primary_variables`` both directly and
        # via ``web._assets_helpers``). The first walk fully determines its
        # contribution; a re-walk would re-apply directives against the already
        # mutated state (spurious warnings, or a hard ValueError for remove), so
        # skip re-walks. The circularity check above stays first so real cycles
        # keep raising instead of being masked as re-includes.
        if bundle in asset_paths.walked_bundles:
            _logger.debug(
                "Bundle %r already walked in this traversal; skipping re-include.",
                bundle,
            )
            return
        asset_paths.walked_bundles.add(bundle)

        # Prepend anchor: files prepended by this bundle are inserted here.
        bundle_start_index = len(asset_paths.list)

        assets = self._get_related_assets(
            [("bundle", "=", bundle)], **assets_params
        ).filtered("active")
        # Partition the (already ``sequence, id``-ordered) recordset into the
        # pre-manifest (sequence < 16) and post-manifest phases.
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
        """Apply a single directive to *asset_paths*.

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

        # ``_get_paths`` is the single resolution entry point (it handles
        # external URLs and ``/web/content`` itself), so no ``can_aggregate``
        # pre-check here.
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
            # ``insert`` skips already-present sources, so an after/before
            # naming a present file is a silent no-op (only ``replace``
            # repositions an existing source). Warn so the ineffective reorder
            # is visible; exclude the anchor itself, legitimately present.
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
                # The path no longer resolves to anything on disk, so the
                # remove is a no-op. Warn (rather than fail): a dead remove
                # hides whether the bundle still needs the directive.
                _logger.warning(
                    "REMOVE directive in bundle %r had no effect: path %r "
                    "resolved to nothing. Either the path is stale (file "
                    "renamed / deleted) and the directive can be dropped, "
                    "or the glob is wrong.",
                    bundle,
                    path_def,
                )
                return
            # A wildcarded remove is set subtraction against the addon's files
            # on DISK, so disk matches absent from the bundle are expected (e.g.
            # mail removes ``discuss/**/*`` from ``web.assets_backend`` before
            # re-adding allowed subsets). Only a LITERAL path remove keeps the
            # strict must-be-present contract.
            asset_paths.remove(paths, bundle, strict=not is_wildcard_glob(path_def))
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

        Returns ``None`` (after warning) when the directive is a no-op -- no
        ``target`` given, or the target resolved to nothing on disk.

        :raises ValueError: via ``AssetPaths.index`` when the anchor resolves to
            a real file simply *not present* in this bundle. Positioning
            relative to an absent anchor is undefined, so it is a hard error.
        """
        if not target:
            # Manifest tuple had an empty target (``("after", "")``): no index
            # can be resolved, so the directive is a no-op. Warn with context.
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
            # The anchor file resolved to nothing (typically renamed/removed).
            # Warn so the directive is not a silent no-op.
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
        """Apply a REPLACE: position *paths* at *target_path*'s slot in source
        order, then drop the target.

        Two subtleties (IRASSET-L1):

        * Already-present sources are pulled out first and re-inserted in source
          order, else ``insert`` would skip them and strand them at their old
          position while the target is removed.
        * If the target is itself among the sources (self-replace, or a glob
          matching it), the target must SURVIVE.
        """
        if not paths:
            # Empty source: the documented "delete the target" idiom.
            _logger.debug(
                "REPLACE source resolved to nothing in bundle %s, "
                "target %s removed without replacement",
                bundle,
                target_path,
            )
        target_in_source = any(p[0] == target_path for p in paths)
        # Sources in original order, excluding the target itself.
        sources = [p for p in paths if p[0] != target_path]
        # Pull out already-present sources so ``insert`` re-adds them in source
        # order rather than skipping them (they are in ``memo``).
        present = [p for p in sources if p[0] in asset_paths.memo]
        if present:
            asset_paths.remove(present, bundle)
        # Re-derive the index AFTER the removals (they may have shifted earlier
        # elements). The target is never in ``present``, so it still anchors.
        target_index = asset_paths.index(target_path, bundle)
        asset_paths.insert(sources, bundle, target_index)
        if not target_in_source:
            asset_paths.remove([(target_path, None, None)], bundle)

    def _get_related_assets(self, domain: list, **kwargs: Any) -> Self:
        """Return assets matching *domain*, regardless of active state.

        Override to filter results (e.g. website-specific deduplication). The
        caller filters on ``active`` afterward.
        """
        # active_test off so website's filter_duplicate can disable some assets;
        # active filtering happens afterward.
        return (
            self.with_context(active_test=False)
            .sudo()
            .search(domain, order="sequence, id")
        )

    def _get_related_bundle(self, target_path_def: str, root_bundle: str) -> str:
        """Return the first bundle directly defining *target_path_def*.

        Useful when generating an 'ir.asset' record to override a specific
        asset.

        :param root_bundle: bundle from which to start the search
        :returns: the first matching bundle, or *root_bundle* as fallback
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
        """Return the active addons for asset resolution.

        Override to filter modules (e.g. discard inactive themes per website).
        """
        return self._get_installed_addons_list()

    @api.model
    @tools.ormcache("addons_tuple")
    def _topological_sort(self, addons_tuple: tuple[str, ...]) -> list[str]:
        """Return addon names sorted by ir.module.module ordering.

        Sorts by application (desc), sequence, name, then topologically to
        respect dependency order.
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
        """Return the set of all installed addon names."""
        return self.env.registry._init_modules.union(
            tools.config["server_wide_modules"]
        )

    def _get_paths(
        self, path_def: str, installed: Collection[str]
    ) -> list[ResolvedPath]:
        """Resolve *path_def* to a list of ``ResolvedPath`` tuples.

        Globs can only occur inside the ``static/`` directory of an installed
        addon. The ``full_path`` field distinguishes the resolution kind: a
        filesystem path (static file), the ``EXTERNAL_ASSET`` sentinel
        (http:// or /web/content), or ``None`` (attachment fallback).

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
                # During module loading, tests may run before all modules are in
                # _init_modules. Skip not-yet-loaded addons rather than crash;
                # once loaded this is unreachable (uninstalled addons have no
                # ir.asset records).
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
                # ``absolute_path`` is canonicalized (globbed from a
                # ``.resolve()``d ``full_path``), so strip the *resolved*
                # addons_path; a raw ``addons_path`` with symlinks or ``..``
                # would fail to strip and yield a malformed web path (IRASSET-M2).
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
                # its ``static/`` dir (e.g. ``/mymod/../other``): blocked by the
                # escape guard, degrading to an attachment URL -- almost always
                # a mistake. Warn so the escape leaves a trace (IRASSET-C4).
                _logger.warning(
                    "IrAsset: path %r resolves outside the static/ directory of "
                    "addon %r; treating it as an attachment URL. This is almost "
                    "certainly a stale or escaping path.",
                    path_def,
                    addon,
                )
            elif addon_manifest:
                # A LITERAL path inside an installed addon's ``static/`` dir
                # matching no bundleable file (a typo, or a non-ASSET_EXTENSIONS
                # file the glob filters out): it degrades to an attachment URL
                # with ``full_path=None`` (IRASSET-C5, mirroring C4). But an
                # attachment row may legitimately shadow a disk-less path (e.g.
                # web's asset_styles_company_report.scss slot, or customized
                # SCSS surviving an upgrade), so only warn when nothing claims
                # the URL.
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
            # Catch every way a malformed command fails to unpack (int ->
            # TypeError, dict -> KeyError, wrong length -> ValueError) and
            # re-raise naming the offending command in the *message* (not just
            # __notes__, which str(exc) hides).
            raise ValueError(f"Malformed asset command: {command!r}") from exc
        return directive, target, path_def


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
        # Bundle names already walked in this traversal; lets ``_fill_asset_paths``
        # skip duplicate sub-bundle includes.
        self.walked_bundles: set[str] = set()

    def index(self, path: str, bundle: str) -> int:
        """Return the index of *path* in the list; raise if absent."""
        if path not in self.memo:
            self._raise_not_found(path, bundle)
        for index, asset in enumerate(self.list):
            if asset.path == path:
                return index
        raise RuntimeError(
            f"Inconsistent asset state: {path!r} in memo but not in list"
        )

    def append(self, paths: list, bundle: str) -> None:
        """Append *paths* to the list (skipping ones already present)."""
        for path, full_path, last_modified in paths:
            if path not in self.memo:
                self.list.append(AssetEntry(path, full_path, bundle, last_modified))
                self.memo.add(path)

    def insert(self, paths: list, bundle: str, index: int) -> None:
        """Insert *paths* at *index* (skipping ones already present)."""
        to_insert = []
        for path, full_path, last_modified in paths:
            if path not in self.memo:
                to_insert.append(AssetEntry(path, full_path, bundle, last_modified))
                self.memo.add(path)
        self.list[index:index] = to_insert

    def remove(self, paths_to_remove: list, bundle: str, strict: bool = True) -> None:
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
        if present:
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
            self.list[:] = [asset for asset in self.list if asset.path not in present]
            self.memo.difference_update(present)
            return

        if requested and strict:
            self._raise_not_found(requested, bundle)

    def _raise_not_found(self, path: str | list[str], bundle: str) -> None:
        raise ValueError(f"File(s) {path} not found in bundle {bundle}")
