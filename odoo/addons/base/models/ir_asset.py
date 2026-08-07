import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from functools import partial
from logging import getLogger
from pathlib import Path
from sys import intern
from types import MappingProxyType
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import ValidationError
from odoo.libs.constants import EXTERNAL_ASSET
from odoo.modules import Manifest
from odoo.tools import misc

from .ir_asset_paths import (
    AFTER_DIRECTIVE,
    APPEND_DIRECTIVE,
    BEFORE_DIRECTIVE,
    DEFAULT_SEQUENCE,
    DIRECTIVES_WITH_TARGET,
    INCLUDE_DIRECTIVE,
    PREPEND_DIRECTIVE,
    REMOVE_DIRECTIVE,
    REPLACE_DIRECTIVE,
    AssetDirective,
    AssetDirectiveError,
    AssetEntry,
    BundleWalk,
    ResolvedPath,
    _glob_static_file,
    can_aggregate,
    fs2web,
    is_wildcard_glob,
    manifest_origin,
    record_origin,
)

_logger = getLogger(__name__)


@dataclass(slots=True)
class Resolution:
    installed: Collection[str]
    assets_params: dict[str, Any] = field(default_factory=dict)
    manifest_assets: Mapping[str, tuple[tuple[str, Any], ...]] = field(
        default_factory=dict
    )
    bundle_assets: dict[str, list] = field(default_factory=dict)
    fetched_bundles: set[str] = field(default_factory=set)
    symlink_memo: dict[tuple[str, str], bool] = field(default_factory=dict)
    resolved_paths: dict[str, tuple[ResolvedPath, ...]] = field(default_factory=dict)
    _manifests: dict[str, Manifest | None] = field(default_factory=dict)
    _addon_roots: dict[str, tuple[str, str]] = field(default_factory=dict)

    def manifest_for(self, addon: str) -> Manifest | None:
        try:
            return self._manifests[addon]
        except KeyError:
            manifest = Manifest.for_addon(addon, display_warning=False)
            self._manifests[addon] = manifest
            return manifest

    def addon_roots(self, addon: str, manifest: Manifest) -> tuple[str, str]:
        try:
            return self._addon_roots[addon]
        except KeyError:
            root = str(Path(manifest.path).resolve())
            roots = (root, root + os.sep + "static")
            self._addon_roots[addon] = roots
            return roots


class IrAsset(models.Model):
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
        registry = self.env.registry
        postcommit = self.env.cr.postcommit
        if not postcommit.data.get("ir_asset_cache_cleared"):
            postcommit.data["ir_asset_cache_cleared"] = True
            postcommit.add(partial(registry.clear_cache, "assets"))
        registry.clear_cache("assets")

    def _get_asset_params(self) -> dict[str, Any]:
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
        addons = self._get_active_addons_list(**assets_params)
        resolution = Resolution(
            installed=self._get_installed_addons_list(),
            assets_params=assets_params,
            manifest_assets=self._get_manifest_assets(tuple(sorted(addons))),
        )
        walk = self._bundle_walk(resolution)
        walk.walk(bundle)
        return tuple(walk.paths.list)

    def _bundle_walk(self, resolution: Resolution) -> BundleWalk:
        return BundleWalk(
            resolve=partial(self._get_paths, resolution=resolution),
            directives_for=partial(self._directives_for, resolution=resolution),
        )

    @api.model
    @tools.ormcache("addons")
    def _get_manifest_assets(
        self, addons: tuple[str, ...]
    ) -> Mapping[str, tuple[tuple[str, Any], ...]]:
        by_bundle: dict[str, list[tuple[str, Any]]] = {}
        for addon in self._topological_sort(addons):
            manifest = Manifest.for_addon(addon)
            if manifest is None:
                continue
            for bundle, commands in manifest["assets"].items():
                by_bundle.setdefault(bundle, []).extend(
                    (addon, command) for command in commands
                )
        return MappingProxyType(
            {bundle: tuple(commands) for bundle, commands in by_bundle.items()}
        )

    def _directives_for(
        self, bundle: str, resolution: Resolution
    ) -> list[AssetDirective]:
        self._fetch_bundle_assets(
            resolution, self._included_bundles(bundle, resolution.manifest_assets)
        )
        early, late = [], []
        for asset in resolution.bundle_assets.get(bundle, ()):
            entry = AssetDirective(
                asset.directive,
                asset.target,
                asset.path,
                record_origin(asset.name, asset.id, asset.directive, asset.path),
            )
            (early if asset.sequence < DEFAULT_SEQUENCE else late).append(entry)

        middle = []
        for addon, command in resolution.manifest_assets.get(bundle, ()):
            origin = manifest_origin(command, addon)
            try:
                directive, target, path_def = self._process_command(command)
            except ValueError as exc:
                raise AssetDirectiveError(
                    f"{exc} — raised by {origin}, declared for bundle {bundle!r}"
                ) from exc
            middle.append(AssetDirective(directive, target, path_def, origin))

        return [*early, *middle, *late]

    def _get_related_assets(self, domain: list, **kwargs: Any) -> Self:
        return (
            self.with_context(active_test=False)
            .sudo()
            .search(domain, order="sequence, id")
        )

    def _filter_bundle_assets(self, assets: Self, **kwargs: Any) -> Self:
        return assets

    def _fetch_bundle_assets(
        self, resolution: Resolution, bundles: Collection[str]
    ) -> None:
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
        self, bundle: str, manifest_assets: Mapping[str, tuple[tuple[str, Any], ...]]
    ) -> set[str]:
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
        return self._get_installed_addons_list()

    @api.model
    @tools.ormcache("addons_tuple")
    def _topological_sort(self, addons_tuple: tuple[str, ...]) -> tuple[str, ...]:
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
        return frozenset(
            self.env.registry._init_modules.union(tools.config["server_wide_modules"])
        )

    def _get_paths(
        self, path_def: str, resolution: Resolution
    ) -> tuple[ResolvedPath, ...]:
        try:
            return resolution.resolved_paths[path_def]
        except KeyError:
            paths = self._resolve_path_def(path_def, resolution)
            resolution.resolved_paths[path_def] = paths
            return paths

    def _resolve_path_def(
        self, path_def: str, resolution: Resolution
    ) -> tuple[ResolvedPath, ...]:
        path_def = fs2web(path_def)
        path_parts = [part for part in path_def.split("/") if part]
        if not path_parts:
            _logger.warning("IrAsset: empty path definition")
            return ()
        if not can_aggregate(path_def):
            return (ResolvedPath(intern(path_def), EXTERNAL_ASSET, -1),)

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
                return ()
            addon_root, static_dir = resolution.addon_roots(addon, addon_manifest)
            full_path = os.path.normpath("/".join([addon_root, *path_parts[1:]]))
            if full_path == static_dir or full_path.startswith(static_dir + os.sep):
                paths_with_timestamps = _glob_static_file(
                    full_path, static_dir, resolution.symlink_memo
                )
                root_len = len(addon_root) + 1
                paths = tuple(
                    ResolvedPath(
                        intern(f"/{addon}/{fs2web(absolute_path[root_len:])}"),
                        intern(absolute_path),
                        timestamp,
                    )
                    for absolute_path, timestamp in paths_with_timestamps
                )
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
            else:
                self._warn_unbacked_attachment_path(
                    path_def, addon if addon_manifest else None
                )
            paths = (ResolvedPath(intern(path_def), None, None),)

        if not paths:
            _logger.warning(
                'IrAsset: the path "%s" did not resolve to anything. %s',
                path_def,
                "It matched no file in the addon's static/ directory."
                if safe_path
                else f"Its first segment {addon!r} is "
                + (
                    "an installed addon, but the pattern points outside that "
                    "addon's static/ directory, which asset globs may not leave."
                    if addon_manifest
                    else "not an installed addon, so the pattern cannot be "
                    "expanded against a static/ directory."
                ),
            )
            return ()
        return paths

    def _warn_unbacked_attachment_path(self, path_def: str, addon: str | None) -> None:
        attachments = self.env["ir.attachment"].sudo()
        if attachments.search_count([("url", "=", path_def)], limit=1):
            return
        where = (
            f"the static/ directory of addon {addon!r}"
            if addon
            else "any addon's static/ directory"
        )
        other_spelling = path_def[1:] if path_def.startswith("/") else f"/{path_def}"
        if attachments.search_count([("url", "=", other_spelling)], limit=1):
            _logger.warning(
                "IrAsset: path %r matches no file in %s, and the attachment "
                "that would back it is registered as %r. The URL is matched "
                "verbatim, so the bundle will not find it -- make the two "
                "spellings agree.",
                path_def,
                where,
                other_spelling,
            )
            return
        _logger.warning(
            "IrAsset: path %r matches no bundleable file in %s (missing file or "
            "non-asset extension) and no attachment claims that URL; treating "
            "it as an attachment URL. This is almost certainly a typo in the "
            "path, or an attachment that was deleted without its ir.asset row.",
            path_def,
            where,
        )

    def _process_command(self, command: str | list) -> tuple[str, str | None, str]:
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
        for label, value in (("path", path_def), ("target", target)):
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"Asset command {command!r} has a non-string {label}: "
                    f"{value!r} ({type(value).__name__})"
                )
        return directive, target, path_def
