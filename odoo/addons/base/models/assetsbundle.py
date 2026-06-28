import functools
import hashlib
import logging
import os
import posixpath
import re
import subprocess
import textwrap
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC
from pathlib import Path
from subprocess import PIPE, Popen
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict

from lxml import etree
from rjsmin import jsmin as rjsmin

from odoo import release
from odoo.api import SUPERUSER_ID, Environment
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.libs.constants import (
    ANY_UNIQUE,
    ODOO_EXTERNAL_LIBS,
    SCRIPT_EXTENSIONS,
    STYLE_EXTENSIONS,
)
from odoo.libs.constants import (
    DOTTED_ASSET_EXTENSIONS as EXTENSIONS,
)
from odoo.libs.profiling.sourcemap_generator import SourceMapGenerator
from odoo.tools import SQL, OrderedSet, misc, profiler
from odoo.tools.assets.esbuild import EsbuildCompiler, EsbuildResult, minify_js
from odoo.tools.assets.esm_bridges import BridgeShimManager
from odoo.tools.assets.esm_graph import (
    _bridge_shim_source,
    _cached_module_classification,
    _parse_odoo_module_header,
    has_module_syntax,
    is_odoo_module,
    url_to_module_path,
)
from odoo.tools.assets.esm_registry import esm_registry, invalidate_esm_registry
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_open, file_path
from odoo.tools.sass_embedded import SassCompileError, find_sass

if TYPE_CHECKING:
    # Model-class imports must stay typing-only: base/models/__init__
    # imports assetsbundle FIRST, and registering ir.attachment before
    # model 'base' exists aborts registry load (house pattern — see
    # ir_attachment.py's own TYPE_CHECKING block).
    from odoo.addons.base.models.ir_attachment import IrAttachment

_logger = logging.getLogger(__name__)

# Structured asset-pipeline logger (odoo.assets.{category}) — flip it on with
# ``--log-handler=odoo.assets:DEBUG`` to trace a bundle's lifecycle: file
# discovery, native-module / import-map assembly, esbuild, and asset
# classification.  Convention, so the two logging systems do not drift: this
# carries the opt-in DEBUG trace plus classification WARNING/ERROR events.
# Always-on operational INFO (attachment persistence) and compiler/error
# reporting stay on the standard module ``_logger`` below — deliberately NOT on
# this namespace, so quieting the trace (``odoo.assets:WARNING``) cannot also
# silence "a bundle was (re)built" or a Sass failure.  The sibling category
# loggers (``odoo.assets.bridge`` / ``.esbuild``) are created on demand inside
# ``odoo.tools.assets.esm_bridges`` / ``odoo.tools.assets.esbuild`` where they are actually
# emitted — this module only writes the ``bundle`` channel.
_bundle_log = get_asset_logger("bundle")


@functools.cache
def _rtlcss_bin() -> str:
    """Resolve the rtlcss executable, handling the Windows ``.cmd`` shim.

    Single source of truth for both the startup probe (:func:`_check_rtlcss`)
    and the invocation (:meth:`AssetsBundle.run_rtlcss`): they used to disagree
    — the probe ran plain ``rtlcss`` while the invocation resolved
    ``rtlcss.cmd`` — so on Windows the probe failed and disabled RTL even when
    the ``.cmd`` shim npm installs was present and usable.
    """
    if os.name == "nt":
        with suppress(OSError):
            return misc.find_in_path("rtlcss.cmd")
    return "rtlcss"


@functools.cache
def _check_rtlcss() -> bool:
    """Probe for the ``rtlcss`` binary. Cached per-process; the warning fires once."""
    try:
        check = Popen([_rtlcss_bin(), "--version"], stdout=PIPE, stderr=PIPE)
        check.communicate(timeout=10)
    except OSError:
        _logger.warning(
            "rtlcss is required for RTL CSS support. Install with: npm install -g rtlcss"
        )
        return False
    except subprocess.TimeoutExpired:
        check.kill()
        check.communicate()
        _logger.warning("rtlcss --version probe timed out; disabling RTL support")
        return False
    # A binary that launches but exits non-zero on ``--version`` is broken (wrong
    # shim, bad install); treat it as unavailable instead of advertising RTL and
    # failing every later ``run_rtlcss`` call.
    if check.returncode:
        _logger.warning(
            "rtlcss --version exited with %s; disabling RTL support",
            check.returncode,
        )
        return False
    return True


@functools.cache
def _rtlcss_config_path() -> str:
    """Absolute path to the rtlcss config, resolved once per process."""
    return file_path("base/data/rtlcss.json")


def _sourcemap_source_root(asset_url: str) -> str:
    """Relative root climbing from the served bundle URL back to ``/``.

    Source map ``sources`` entries are site-absolute paths; the browser
    resolves them against ``sourceRoot``, so the root must contain one
    ``..`` per directory segment of the bundle URL.
    """
    return "/".join(".." for _ in range(len(asset_url.split("/")) - 2)) + "/"


class BundleFileSpec(TypedDict):
    """One bundle source file, as collected by ``ir_qweb._get_asset_content``.

    ``content`` is the inline source (empty string for file-backed assets,
    where ``filename`` points at the file on disk); the constructor renames
    it to the asset's ``inline`` attribute.
    """

    url: str
    filename: str | None
    content: str
    last_modified: NotRequired[float | None]


class NativeModuleData(TypedDict):
    """The import-map / preload payload returned by ``get_native_module_data``.

    Fixed shape consumed at three ir_qweb sites; the TypedDict documents the
    contract and lets a type checker catch a misspelled key at the call site.
    """

    import_map: dict[str, str]
    preload_urls: list[str]
    bridge_import_map: dict[str, str]


# ``xml()`` returns a discriminated union of blocks; the ``type`` literal is the
# discriminator the consumer (``generate_xml_bundle``) branches on. Modelling it
# as two TypedDicts (instead of ``dict[str, Any]``) makes a typo in either the
# discriminator or a payload key a static error, not a silent KeyError at render.
class TemplatesBlock(TypedDict):
    """A run of primary / parentless templates, in source order."""

    type: Literal["templates"]
    # (element, asset url, t-inherit parent name | None)
    templates: list[tuple[etree._Element, str | None, str | None]]


class ExtensionsBlock(TypedDict):
    """A run of ``t-inherit-mode="extension"`` templates, grouped by parent."""

    type: Literal["extensions"]
    # {parent template name: [(element, asset url), ...]}
    extensions: dict[str, list[tuple[etree._Element, str | None]]]


XMLBlock = TemplatesBlock | ExtensionsBlock


# Two error families, deliberately kept separate:
#   * AssetError   — an asset's content could not be obtained, decoded or parsed
#                    (catchable as one group via ``except AssetError``)
#   * CompileError — a preprocessor subprocess (Sass/rtlcss) failed; caught
#                    explicitly alongside ``SassCompileError``, never via the
#                    ``except AssetError`` net, hence a separate RuntimeError.
class CompileError(RuntimeError):
    """A stylesheet preprocessor (Sass/rtlcss) failed or timed out."""


class AssetError(Exception):
    """An asset's content could not be obtained, decoded or parsed."""


class AssetNotFoundError(AssetError):
    """The asset's backing file or attachment does not exist."""


class XMLAssetError(AssetError):
    """An XML template asset failed to parse or validate."""


def _run_cli_pipe(argv: Sequence[str], source: str, timeout_s: int) -> str:
    """Run *argv* feeding *source* on stdin; return its stdout.

    Shared subprocess plumbing for the stylesheet CLIs (Sass, rtlcss):
    launch, feed, bounded wait, kill-and-reap on timeout.  Every failure
    shape raises ``CompileError``; callers translate it into their own
    degradation policy (propagate vs ``css_errors`` + degraded output).

    :param argv: command line; ``argv[0]`` names the tool in errors
    :param source: text piped to stdin
    :param timeout_s: budget — a hung binary must not pin a worker
    :raises CompileError: launch failure, timeout, or non-zero exit
    """
    try:
        proc = Popen(argv, stdin=PIPE, stdout=PIPE, stderr=PIPE, encoding="utf-8")
    except OSError:
        raise CompileError(f"Could not execute command {argv[0]!r}") from None
    try:
        out, err = proc.communicate(input=source, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise CompileError(f"{argv[0]!r} timed out after {timeout_s}s") from None
    if proc.returncode:
        cmd_output = out + err
        if not cmd_output:
            cmd_output = f"Process exited with return code {proc.returncode}\n"
        raise CompileError(cmd_output)
    return out


# CSS string-literal / comment tokenizer — the two spans every whole-text CSS
# rewrite (url(), @import, appearance) and the minifier must treat as opaque.
# Alternation order matters: a ``"`` inside a comment is consumed by the comment
# arm, a ``/*`` inside a string by the string arm (a left-to-right scan takes
# whichever opens first). One definition, referenced by
# ``StylesheetAsset._minify_css_body`` (masking) and
# ``_rewrite_css_outside_strings`` (skip-in-place) so the two never drift.
_CSS_STRING_OR_COMMENT = re.compile(
    r"""/\*.*?\*/|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'""",
    re.DOTALL,
)


def _rewrite_css_outside_strings(
    target: re.Pattern, repl: Callable[[re.Match], str], text: str
) -> str:
    """Apply ``repl`` to ``target`` matches that lie in CSS *code* only.

    A single left-to-right scan consumes string-literal and comment spans first
    (the same tokenizer strategy as :meth:`StylesheetAsset._minify_css_body`),
    so a ``url()`` / ``@import`` / ``appearance:`` written *inside* a
    ``content: "…"`` value or a comment is passed through untouched instead of
    being rewritten — the string-unawareness the whole-text ``re.sub`` calls
    used to have (characterized as "known limitations" before this).
    ``target``'s own capture groups reach ``repl`` unchanged: the scanner adds
    none of its own.

    A real ``url("x")`` is still rewritten — its match *starts* at the ``url(``
    token (code); only the inner ``"x"`` is a protected span, which the rewrite
    never needs to enter — so preload byte-matching is unaffected.
    """
    # DOTALL is scoped to the string/comment arm via ``(?s:...)`` — only that
    # arm needs it (block comments ``/\*.*?\*/`` and ``\\.`` line continuations
    # span newlines). The previous ``target.flags | re.DOTALL`` forced DOTALL
    # onto the WHOLE combined pattern, silently redefining any ``.`` a future
    # ``target`` might carry; scoping confines it so the caller's pattern keeps
    # exactly the flags it was compiled with. ``(?s:...)`` is non-capturing, so
    # ``target``'s own group numbers are unchanged.
    scanner = re.compile(
        f"(?s:{_CSS_STRING_OR_COMMENT.pattern})|{target.pattern}",
        target.flags,
    )

    def _dispatch(match: re.Match) -> str:
        token = match.group(0)
        if token[:2] == "/*" or token[:1] in ("'", '"'):
            return token  # protected span — pass through verbatim
        return repl(match)

    return scanner.sub(_dispatch, text)


class AssetAttachmentStore:
    """Persist, look up and version-clean one bundle's ``ir.attachment`` artifacts.

    Split out of :class:`AssetsBundle` so the raw-SQL attachment layer — and its
    concurrency handling (``SKIP LOCKED`` deletes, the parallel-transaction
    dedup, the cross-params fallback copy) — lives behind one boundary and is
    testable without a full bundle. Holds no version state: the bundle's version
    is read through the ``version_provider`` callback, leaving
    :class:`AssetsBundle` the single source of truth for checksums.
    """

    # Bundles whose rebuild broadcasts a ``bundle_changed`` bus message.
    TRACKED_BUNDLES = ("web.assets_web",)

    # Stylesheet artifact extensions accepted by ``is_css``.
    _CSS_EXTENSIONS = frozenset({"css", "min.css", "css.map"})

    # Persistable bundle artifacts and their served mimetype; doubles as
    # the ``save_attachment`` extension whitelist (one source of truth —
    # the guard and the lookup used to encode this twice and drift).
    # ``xml`` / ``min.xml`` round out the artifact set and back the
    # ``save_attachment`` guard; the current production ESM-template path
    # persists through ``ir_qweb._save_esm_attachment`` instead, so they are
    # only reached via direct ``save_attachment`` calls (and their tests).
    _ATTACHMENT_MIMETYPES = MappingProxyType(
        {
            "js": "application/javascript",
            "min.js": "application/javascript",
            "js.map": "application/json",
            "css": "text/css",
            "min.css": "text/css",
            "css.map": "application/json",
            "xml": "text/xml",
            "min.xml": "text/xml",
        }
    )

    def __init__(
        self,
        env: Environment,
        name: str,
        *,
        assets_params: dict[str, Any],
        rtl: bool,
        autoprefix: bool,
        version_provider: Callable[[str], str],
    ) -> None:
        """Bind the store to a bundle's identity and version source.

        :param version_provider: returns the 7-hex version for an asset type
            (``"js"`` / ``"css"``); keeps the store out of checksum logic.
        """
        self.env = env
        self.name = name
        self.assets_params = assets_params
        self.rtl = rtl
        self.autoprefix = autoprefix
        self._version = version_provider

    @staticmethod
    def _like_escape(literal: str) -> str:
        """Escape LIKE metacharacters so *literal* matches only itself.

        Bundle names routinely contain ``_`` (``web.assets_web``), which is
        a single-char wildcard in SQL ``LIKE``: unescaped, the pattern for
        ``test.audit_b`` also matches a sibling ``test.auditXb`` — letting
        ``_clean_attachments`` delete the sibling's attachment and making
        ``get_attachments(ignore_version=True)`` return several names
        (which breaks the singleton ``raw`` read in ``css()``'s degraded
        path).  PostgreSQL's default escape character is the backslash.
        """
        return literal.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def is_css(self, extension: str) -> bool:
        """Whether ``extension`` denotes a stylesheet artifact."""
        return extension in self._CSS_EXTENSIONS

    def get_asset_url(self, unique: str, extension: str) -> str:
        """Build the real attachment URL for one bundle artifact."""
        return self._asset_url(unique, extension, ignore_params=False)

    def get_asset_url_pattern(
        self,
        unique: str = ANY_UNIQUE,
        extension: str = "%",
        ignore_params: bool = False,
    ) -> str:
        """Build a SQL ``=like`` pattern over this bundle's attachment URLs.

        ``%`` wildcards may appear in ``unique`` (``ANY_UNIQUE``) and
        ``extension``; ``ignore_params`` widens the match across
        assets-params variants (website, lang).  The bundle *name* is a
        literal: its LIKE metacharacters are escaped (see
        :meth:`_like_escape`), so the pattern never crosses into a
        sibling bundle's attachments.  Split from :meth:`get_asset_url`
        so URL construction and SQL-pattern construction stop sharing
        one signature.
        """
        return self._asset_url(unique, extension, ignore_params, pattern=True)

    def _asset_url(
        self,
        unique: str,
        extension: str,
        ignore_params: bool,
        pattern: bool = False,
    ) -> str:
        """Shared URL assembly for :meth:`get_asset_url` and the pattern form.

        With ``pattern=True`` the bundle name is LIKE-escaped; ``unique``
        and ``extension`` are left untouched — their wildcards
        (``ANY_UNIQUE``, the ``"%"`` extension default) are intentional,
        and their concrete values (7-hex unique, the
        ``_ATTACHMENT_MIMETYPES`` extensions) contain no metacharacters.
        """
        direction = ".rtl" if self.is_css(extension) and self.rtl else ""
        autoprefixed = (
            ".autoprefixed" if self.is_css(extension) and self.autoprefix else ""
        )
        name = self._like_escape(self.name) if pattern else self.name
        bundle_name = f"{name}{direction}{autoprefixed}.{extension}"
        return self.env["ir.asset"]._get_asset_bundle_url(
            bundle_name, unique, self.assets_params, ignore_params
        )

    def _attachment_values(
        self, *, name: str, mimetype: str, raw: bytes, url: str
    ) -> dict[str, Any]:
        """Build the ``ir.attachment`` create payload for one bundle artifact.

        The single write-side source for both :meth:`save_attachment` and the
        cross-params fallback copy in :meth:`get_attachments`. The identity
        columns set here — ``res_model='ir.ui.view'``, ``res_id`` (the
        ``Many2oneReference`` integer coerces the ``False`` to ``0``),
        ``public=True``, and ``create_uid=SUPERUSER_ID`` via the creating user
        — are exactly the columns :meth:`get_attachments` / :meth:`_clean_attachments`
        filter on, so the read and write halves cannot drift. ``name`` /
        ``mimetype`` / ``raw`` / ``url`` are the per-artifact payload.
        """
        return {
            "name": name,
            "mimetype": mimetype,
            "res_model": "ir.ui.view",
            "res_id": False,
            "type": "binary",
            "public": True,
            "raw": raw,
            "url": url,
        }

    def _unlink_attachments(self, attachments: IrAttachment) -> None:
        """Unlinks attachments without actually calling unlink, so that the ORM cache is not cleared.

        Specifically, if an attachment is generated while a view is rendered, clearing the ORM cache
        could unload fields loaded with a sudo(), and expected to be readable by the view.
        Such a view would be website.layout when main_object is an ir.ui.view.
        """
        fname_by_id = {
            attach.id: attach.store_fname
            for attach in attachments
            if attach.store_fname
        }
        table = SQL.identifier(attachments._table)
        self.env.cr.execute(
            SQL(
                """DELETE FROM %s WHERE id IN (
            SELECT id FROM %s WHERE id = ANY(%s) FOR NO KEY UPDATE SKIP LOCKED
        ) RETURNING id""",
                table,
                table,
                list(attachments.ids),
            )
        )
        # ``SKIP LOCKED`` may leave rows in place; only mark the filestore
        # entries of rows that were actually deleted (the GC's reference
        # check would catch a wrong mark, but don't lean on the backstop).
        deleted_ids = {row[0] for row in self.env.cr.fetchall()}
        to_delete = {
            fname
            for attach_id, fname in fname_by_id.items()
            if attach_id in deleted_ids
        }
        for fpath in to_delete:
            # key-axis dispatch: deletes follow the store key's backend
            attachments._storage_delete(fpath)

    def _clean_attachments(self, extension: str, keep_url: str) -> None:
        """Delete outdated ir.attachment records for this bundle before
        saving a fresh one.

        When `extension` is js we need to check that we are deleting a different version (and not *any*
        version) because, as one of the creates in `save_attachment` can trigger a rollback, the
        call to `_clean_attachments` is made at the end of the method to avoid the rollback
        of an ir.attachment unlink (because we cannot rollback a removal on the filestore), thus we
        must exclude the current bundle.
        """
        ira = self.env["ir.attachment"]
        to_clean_pattern = self.get_asset_url_pattern(extension=extension)
        # Mirror the identity columns ``get_attachments`` reads on (create_uid /
        # res_model / res_id, set by ``_attachment_values``): the delete must
        # never reach a row the read would not surface — otherwise a public
        # attachment that merely shares the URL pattern (a different creator or
        # res_model) would be GC'd here despite being invisible to the serving
        # path. With this the read and delete halves cover the exact same set.
        domain = [
            ("url", "=like", to_clean_pattern),
            ("url", "!=", keep_url),
            ("public", "=", True),
            ("res_model", "=", "ir.ui.view"),
            ("res_id", "=", 0),
            ("create_uid", "=", SUPERUSER_ID),
        ]

        attachments = ira.sudo().search(domain)
        if attachments:
            _logger.info(
                "Deleting attachments %s (matching %s) because it was replaced with %s",
                attachments.ids,
                to_clean_pattern,
                keep_url,
            )
            self._unlink_attachments(attachments)

    def get_attachments(
        self, extension: str, ignore_version: bool = False
    ) -> IrAttachment:
        """Return the ir.attachment records for a given bundle. Mitigates an issue where
        parallel transactions generate the same bundle: while the file is not
        duplicated on the filestore (as it is stored according to its hash), there are multiple
        ir.attachment records referencing the same version of a bundle. As we don't want to source
        the same bundle several times when rendering, we group our ir.attachment records
        by file name and only return the one with the max id for each group.

        :param extension: file extension (js, min.js, css)
        :param ignore_version: if ignore_version, the url contains a version => web/assets/%/name.extension
                                (the second '%' corresponds to the version),
                               else: the url contains a version equal to that of the bundle version
                                => web/assets/<version>/name.extension.
        """
        unique = (
            ANY_UNIQUE
            if ignore_version
            else self._version("css" if self.is_css(extension) else "js")
        )
        url_pattern = self.get_asset_url_pattern(unique=unique, extension=extension)
        query = """
             SELECT max(id)
               FROM ir_attachment
              WHERE create_uid = %s
                AND url like %s
                AND res_model = 'ir.ui.view'
                AND res_id = 0
                AND public = true
           GROUP BY name
           ORDER BY name
        """
        self.env.cr.execute(SQL(query, SUPERUSER_ID, url_pattern))

        attachment_ids = [r[0] for r in self.env.cr.fetchall()]
        if not attachment_ids and not ignore_version:
            fallback_url_pattern = self.get_asset_url_pattern(
                unique=unique,
                extension=extension,
                ignore_params=True,
            )
            # The cross-params fallback only finds anything when an
            # ``_get_asset_bundle_url`` override (website) makes the
            # ``ignore_params=True`` pattern wider than the primary one. In base
            # the two patterns are byte-identical, so re-running the query is a
            # guaranteed-empty second round-trip on every cache miss — skip it.
            similar_attachment_ids = []
            if fallback_url_pattern != url_pattern:
                self.env.cr.execute(SQL(query, SUPERUSER_ID, fallback_url_pattern))
                similar_attachment_ids = [r[0] for r in self.env.cr.fetchall()]
            if similar_attachment_ids:
                similar = (
                    self.env["ir.attachment"].sudo().browse(similar_attachment_ids[0])
                )
                _logger.info(
                    "Found a similar attachment for %s, copying from %s",
                    url_pattern,
                    similar.url,
                )
                # The pattern LIKE-escapes the bundle name (``\_``); the
                # stored URL must be the real, unescaped one.
                url = self.get_asset_url(unique=unique, extension=extension)
                values = self._attachment_values(
                    name=similar.name,
                    mimetype=similar.mimetype,
                    raw=similar.raw,
                    url=url,
                )
                attachment = (
                    self.env["ir.attachment"].with_user(SUPERUSER_ID).create(values)
                )
                attachment_ids = attachment.ids
                self._clean_attachments(extension, url)

        return self.env["ir.attachment"].sudo().browse(attachment_ids)

    def save_attachment(self, extension: str, content: str) -> IrAttachment:
        """Record the given bundle in an ir.attachment and delete
        all other ir.attachments referring to this bundle (with the same name and extension).

        :param extension: extension of the bundle to be recorded
        :param content: bundle content to be recorded

        :return: the created ir.attachment record.
        """
        mimetype = self._ATTACHMENT_MIMETYPES.get(extension)
        if mimetype is None:
            raise ValueError(f"Invalid asset extension {extension!r}")
        ira = self.env["ir.attachment"]

        # The LTR/RTL (and autoprefixed) variants are distinguished by the
        # URL, not the name: ``_asset_url`` injects ``.rtl`` / ``.autoprefixed``
        # segments, and both ``get_attachments`` and ``_clean_attachments``
        # match on that direction-scoped URL pattern — so the two variants
        # never collide despite sharing this ``name``. (Upstream encoded the
        # direction in the name; this fork moved it into the URL.)
        fname = f"{self.name}.{extension}"
        unique = self._version("css" if self.is_css(extension) else "js")
        url = self.get_asset_url(
            unique=unique,
            extension=extension,
        )
        values = self._attachment_values(
            name=fname, mimetype=mimetype, raw=content.encode("utf-8"), url=url
        )
        attachment = ira.with_user(SUPERUSER_ID).create(values)

        _logger.info(
            "Generating a new asset bundle attachment %s (id:%s)",
            attachment.url,
            attachment.id,
        )

        self._clean_attachments(extension, url)

        # For end-user assets (common and backend), send a message on the bus
        # to invite the user to refresh their browser
        if "bus.bus" in self.env and self.name in self.TRACKED_BUNDLES:
            self.env["bus.bus"]._sendone(
                "broadcast",
                "bundle_changed",
                {"server_version": release.version},
            )
            _logger.debug("Asset Changed: bundle: %s -- version: %s", self.name, unique)

        return attachment


class CssPipeline:
    """Compile one bundle's stylesheets to CSS: SCSS, autoprefix, RTL, minify.

    Split out of :class:`AssetsBundle` so the stylesheet preprocessor — Sass
    compilation, the ``@import`` sanitizer, autoprefixing, the rtlcss pass, the
    per-file split/minify reassembly, and the degraded-error banner — lives
    behind one boundary, with its subprocess error policy, testable without
    attachment I/O.

    Unlike :class:`AssetAttachmentStore` (which deliberately holds no bundle
    reference), this pipeline IS bound to its bundle: :meth:`preprocess` reads
    the bundle's ``stylesheets`` and rebuilds the bundle's ``css_errors``. It
    does NOT mutate the source ``stylesheets`` list: the Sass-hoisted
    ``@at-rules`` fragment and the per-file compiled content are assembled into
    the pipeline's own :attr:`_rendered_assets`, which ``css_with_sourcemap``
    reads back. Keeping the source list immutable makes :meth:`preprocess` a
    pure rebuild — no idempotency guard, and ``get_checksum`` sees the same
    assets no matter when it runs. The bundle keeps one pipeline
    (``AssetsBundle._css``) so that render list survives the ``preprocess`` →
    ``css_with_sourcemap`` call sequence.
    """

    # @import sanitizer pattern. ``([^;{]*;?)`` (group 3) captures the post-quote
    # tail (media query, optional ``;``) up to the statement terminator — like
    # ``AssetsBundle.rx_css_import``. Keeping the trailing media query inside the
    # match makes the dedup key media-aware: two imports of the same url with
    # DIFFERENT media stay distinct, and a deduped removal drops the media query
    # with the statement instead of orphaning it. The ``{`` boundary stops a
    # missing-``;`` import from swallowing a following rule body.
    rx_preprocess_imports = re.compile(r"""(@import\s*['"]([^'"]+)['"]([^;{]*;?))""")
    # SCSS-aware scanner driving the @import sanitizer (:meth:`compile_css`). An
    # ``@import`` written inside a comment or string literal is NOT a directive
    # and must be passed through verbatim: otherwise a commented-out
    # ``// @import "x";`` both trips the local-import security check AND poisons
    # the dedup set, silently dropping a real later import of the same partial.
    # This is the SCSS analogue of :func:`_rewrite_css_outside_strings`, but it
    # also consumes the Sass ``//`` line comment — a Sass-only construct that
    # helper deliberately omits, because ``//`` is ordinary text in plain CSS
    # (e.g. ``url(//cdn/...)``) and must not be read as a comment there. The
    # shared ``_CSS_STRING_OR_COMMENT`` supplies the block-comment + string arms
    # (one source), ``//[^\n]*`` adds the line comment, and
    # ``rx_preprocess_imports`` supplies the directive grammar (also one source).
    # Only the directive arm carries capture groups, so its ref / tail keep group
    # numbers 2 / 3 in the combined pattern. A left-to-right scan consumes
    # whichever span opens first, so a ``//`` inside a string is taken by the
    # string arm and a ``"`` inside a ``//`` comment is taken by the line arm.
    # DOTALL is scoped to the block-comment/string arm (``(?s:...)``): the line
    # arm (``//[^\n]*``) and the directive arm carry no ``.``, and confining the
    # flag stops it from silently redefining a ``.`` added to either arm later
    # (mirrors the scoping in :func:`_rewrite_css_outside_strings`).
    _rx_import_scanner = re.compile(
        rf"//[^\n]*|(?s:{_CSS_STRING_OR_COMMENT.pattern})|{rx_preprocess_imports.pattern}",
    )
    # The split marker is namespaced (``odoo-split:``) so it cannot alias a
    # legitimate CSS loud comment (``/*! <token> */``), which Sass and the
    # minifier deliberately preserve: a bare ``/*! <hex> */`` (e.g. a build-hash
    # stamp) used to be misread as a fragment boundary and abort the whole
    # bundle's CSS compile.  Kept in lockstep with ``StylesheetAsset.get_source``.
    rx_css_split = re.compile(r"/\*! odoo-split:([a-f0-9-]+) \*/")

    # rtlcss subprocess budget; a hung binary must not pin a worker.
    _RTLCSS_TIMEOUT_S: int = 60

    # Marker separating the carried-over previous CSS from the appended error
    # banner. It MUST be used by both the split (which strips a prior banner so
    # repeated errors don't stack) and the join (which re-adds it) — see
    # :meth:`_render_css_error_banner`; a single constant keeps the two in lockstep.
    _CSS_ERROR_HEADER = "\n\n/* ## CSS error message ##*/"

    def __init__(self, bundle: AssetsBundle) -> None:
        """Bind the pipeline to the bundle whose stylesheets it transforms."""
        self._bundle = bundle
        # The ordered render list :meth:`preprocess` assembles — the optional
        # Sass-hoisted @at-rules fragment (as a synthetic StylesheetAsset)
        # followed by the bundle's stylesheets, each carrying its compiled
        # content. ``css_with_sourcemap`` reads it back. Held here instead of
        # injected into ``bundle.stylesheets`` so preprocess never mutates the
        # bundle's source list.
        self._rendered_assets: list[StylesheetAsset] = []

    def preprocess(self) -> str:
        """Compile SCSS to CSS, apply RTL and autoprefixing.

        All SCSS files are concatenated and compiled as a single
        document (required because Sass variables are globally scoped with
        ``@import``).  UUID markers (``/*! odoo-split:<uuid> */``) injected by
        ``get_source()`` survive Sass compilation and are used to split the
        compiled output back into per-file fragments — each fragment is
        reassigned to its source asset so that per-file headers and source
        maps work correctly.
        """
        bundle = self._bundle
        # preprocess is the single authority on ``css_errors``: it rebuilds the
        # list from scratch on every call — bundle-level compile/rtl failures
        # (appended below) plus each StylesheetAsset's own fetch errors
        # (harvested below) — so a re-run can never double-report.
        bundle.css_errors.clear()
        # Every call rebuilds the render list from scratch, mirroring the
        # ``css_errors.clear()`` above. preprocess never mutates
        # ``bundle.stylesheets``, so re-runs are idempotent by construction:
        # there is no injected @at-rules asset to drop first, and (under RTL)
        # no stale fragment can re-enter the compile input via the
        # ``plain_css_assets`` filter — the old failure modes a guard once fixed.
        self._rendered_assets = []
        if not bundle.stylesheets:
            return ""

        # Reset per-asset state so the rebuild-from-source contract holds for
        # the leaves too. Each StylesheetAsset records fetch/rewrite errors in
        # its own ``errors`` list and caches fetched content in ``_content``;
        # ``css_errors`` is cleared above but then *extended* from those lists,
        # and ``get_source()`` re-reads uncached (it bypasses the ``content``
        # property to recompile from the original source). Without clearing
        # them here a second call double-reports every leaf fetch error (the
        # ``css_errors.clear()`` above is not enough) and could reuse a stale
        # fragment. Resetting ``_content`` keeps minify()/get_source() in step
        # so a cleared error is re-recorded this run rather than silently lost.
        for asset in bundle.stylesheets:
            asset.errors.clear()
            asset._content = None

        compiled = ""
        assets = [a for a in bundle.stylesheets if isinstance(a, PreprocessedCSS)]
        if assets:
            # The whole concatenation is compiled through ONE compiler (Sass
            # needs the global ``@import`` scope), so ``assets[0].compile`` must
            # be every asset's — i.e. all preprocessed assets share one dialect.
            # Only ScssStylesheetAsset exists today; enforce the invariant so a
            # future second PreprocessedCSS dialect trips here instead of being
            # silently compiled through the first asset's compiler. A plain
            # ``raise`` (not ``assert``) so it still fires under ``python -O``,
            # where asserts are stripped — this guards output correctness, not a
            # mere debug check.
            dialects = {type(a) for a in assets}
            if len(dialects) != 1:
                raise RuntimeError(
                    f"bundle {bundle.name!r} mixes preprocessed-CSS dialects "
                    f"{sorted(t.__name__ for t in dialects)}"
                )
            source = "\n".join(asset.get_source() for asset in assets)
            compiled = self.compile_css(assets[0].compile, source)

        if bundle.autoprefix:
            compiled = self._autoprefix_css(compiled)

        # RTL: merge plain CSS into compiled output, then transform the whole
        if bundle.rtl:
            plain_css_assets = [
                asset
                for asset in bundle.stylesheets
                if not isinstance(asset, PreprocessedCSS)
            ]
            compiled += "\n".join(asset.get_source() for asset in plain_css_assets)
            compiled = self.run_rtlcss(compiled)

        # A bundle-level failure (Sass/rtl compile error, or a forbidden
        # @import) recorded an error *before* the per-file split, leaving
        # ``compiled`` empty. ``css_errors`` can only hold such bundle-level
        # entries at this point — leaf fetch errors live on each asset's own
        # ``errors`` list and are harvested later — so a non-empty list here
        # unambiguously means compilation failed and nothing usable was
        # produced. Short-circuit the split + minify reassembly entirely.
        compile_failed = bool(bundle.css_errors)
        if compile_failed:
            # A bundle-level failure produced no usable ``compiled`` output, so
            # the per-file split assigns no fragments. Short-circuit before the
            # ``minify()`` reassembly: that pass would re-fetch — and so
            # re-error — every leaf whose ``_content`` the empty ``compiled``
            # left unset, double-reporting its fetch error within this single
            # call, and its assembled (raw, uncompiled) result is discarded
            # anyway. Harvest the leaf errors recorded during ``get_source()``
            # and return "": "nothing usable, see css_errors".
            for asset in bundle.stylesheets:
                bundle.css_errors.extend(asset.errors)
            return ""

        # Split compiled output back into per-file fragments using UUID markers
        fragments = self.rx_css_split.split(compiled)
        at_rules = fragments.pop(0)
        # Sass moves @at-rules (e.g. @charset) to the top for CSS 2.1
        # compatibility. They have no source asset, so wrap them in a synthetic
        # StylesheetAsset and prepend it to the RENDER list — never to
        # ``bundle.stylesheets``. Keeping the bundle's source list immutable is
        # what makes preprocess a pure rebuild (idempotent without a guard). The
        # bundle version is unaffected either way: ``get_checksum`` reads the
        # ``__init__`` snapshot (``bundle._version_assets``), not this list.
        rendered = list(bundle.stylesheets)
        if at_rules:
            rendered.insert(0, StylesheetAsset(bundle, inline=at_rules))
        self._rendered_assets = rendered

        # Per-file fragments are matched back to their SOURCE assets only — the
        # synthetic @at-rules asset carries its content inline, never via a
        # split marker.
        assets_by_id = {a.id: a for a in bundle.stylesheets}
        # ``rx_css_split`` yields ``marker, content, marker, content, …``;
        # pair-iterate instead of ``pop(0)`` in a loop, which is O(N²) on a
        # bundle that splits into hundreds of fragments.
        marker_iter = iter(fragments)
        for asset_id, content in zip(marker_iter, marker_iter, strict=True):
            asset = assets_by_id.get(asset_id)
            if asset is None:
                raise RuntimeError(
                    f"CSS asset {asset_id!r} not found in stylesheets — "
                    "compiled output is out of sync with the asset list"
                )
            asset._content = content

        bundle_css = "\n".join(asset.minify() for asset in self._rendered_assets)
        # Harvest each asset's own fetch/rewrite errors. The minify pass above
        # (and the get_source() reads earlier) is what triggers content
        # fetching, so every asset's ``errors`` list is fully populated by now.
        # The bundle owns ``css_errors`` and the pipeline collects from the
        # leaves here, rather than each StylesheetAsset reaching up to append.
        # A bundle-level compile failure already returned "" above; reaching
        # here means compilation succeeded, so a leaf-only fetch error still
        # ships the partial bundle (the good assets compiled fine), and css()
        # banners on the harvested error (pinned by
        # test_bundle_harvests_asset_errors).
        for asset in bundle.stylesheets:
            bundle.css_errors.extend(asset.errors)
        return bundle_css

    def compile_css(self, compiler: Callable[[str], str], source: str) -> str:
        """Sanitize @import rules, remove duplicates, then compile.

        Only @import statements in actual SCSS *code* are sanitized: ones
        sitting inside a comment or string literal are passed through
        verbatim (see :attr:`_rx_import_scanner`).
        """
        bundle = self._bundle
        seen_imports: set[str] = set()

        def sanitize_import(matchobj: re.Match) -> str:
            token = matchobj.group(0)
            # Comment / string span: the ``@import`` inside it is not a
            # directive — return it untouched. This is what stops a commented
            # ``// @import "x";`` from raising a spurious security error and
            # from poisoning ``seen_imports`` (which would silently drop a real
            # later import of the same partial).
            if token[:2] in ("/*", "//") or token[:1] in ("'", '"'):
                return token
            ref = matchobj.group(2)
            line = f'@import "{ref}"{matchobj.group(3)}'
            # Dedup FIRST, media-aware: ``line`` reconstructs the full statement
            # (group 3 carries the trailing media query), so the key treats the
            # same url with different media as distinct. Deduping ahead of the
            # security check means a forbidden import repeated across several
            # concatenated files is reported ONCE, not once per occurrence —
            # ``css_errors`` is joined verbatim into the degraded-CSS banner, so
            # N copies of the same line used to stack into N banner lines (and
            # N identical server warnings). Re-importing a library partial is
            # likewise the normal SCSS case and dropped silently.
            if line in seen_imports:
                return ""
            seen_imports.add(line)
            # Security: reject genuine local/relative imports — a dotted
            # filename (``foo.scss``) or a path-like ref (``./``, ``/``,
            # ``~``). These must be pulled in through the assets bundle,
            # not via a raw @import the compiler resolves off the load path.
            if "." in ref or ref.startswith((".", "/", "~")):
                msg = (
                    f"Local import {ref!r} is forbidden for security reasons."
                    " Remove @import statements from custom files;"
                    " in Odoo, import files via the assets bundle instead."
                )
                _logger.warning(msg)
                bundle.css_errors.append(msg)
                return ""
            return line

        source = self._rx_import_scanner.sub(sanitize_import, source)

        try:
            return compiler(source).strip()
        except (CompileError, SassCompileError) as e:
            error = self._format_compiler_error(str(e))
            _logger.warning(error)
            bundle.css_errors.append(error)
            return ""

    # Vendor-prefix matcher for the ``appearance`` property. Handles both
    # expanded ("  appearance: none;") and compressed ("{appearance:none}")
    # Dart Sass output.  Two correctness details:
    #   * the value group is ``[\w-]+`` (not ``\w+``) so a hyphenated value
    #     like ``menulist-button`` is carried into the prefixed copies intact
    #     instead of being truncated to ``menulist``;
    #   * an optional ``!important`` is captured and replicated onto the
    #     ``-webkit-``/``-moz-`` declarations — otherwise the prefixed copies
    #     silently drop it and lose to a competing rule (notably the common
    #     WebKit form-control reset ``appearance: none !important``).
    # ``-webkit-appearance``/``-moz-appearance`` already present are left
    # untouched: their ``appearance`` is preceded by ``-``, outside the
    # ``[{; \t]`` lead-in class.
    _RX_APPEARANCE = re.compile(r"([{; \t])appearance:\s*([\w-]+)(\s*!important)?(;?)")

    @classmethod
    def _autoprefix_css(cls, source: str) -> str:
        """Post-process compiled CSS to add required vendor prefixes.

        Intentionally minimal — only the ``appearance`` property is
        handled; this is not a general-purpose autoprefixer. String-aware
        (via :func:`_rewrite_css_outside_strings`): an ``appearance:`` written
        inside a ``content: "…"`` string value is left untouched.
        """

        def _prefix(match: re.Match) -> str:
            lead, value = match.group(1), match.group(2)
            important = match.group(3) or ""
            semicolon = match.group(4)
            return (
                f"{lead}-webkit-appearance:{value}{important};"
                f"-moz-appearance:{value}{important};"
                f"appearance:{value}{important}{semicolon}"
            )

        return _rewrite_css_outside_strings(cls._RX_APPEARANCE, _prefix, source.strip())

    def run_rtlcss(self, source: str) -> str:
        """Transform CSS for right-to-left languages using rtlcss."""
        if not _check_rtlcss():
            return source

        cmd = [_rtlcss_bin(), "-c", _rtlcss_config_path(), "-"]

        try:
            out = _run_cli_pipe(cmd, source, self._RTLCSS_TIMEOUT_S)
        except CompileError as e:
            error = self._format_compiler_error(str(e))
            _logger.warning("%s", error)
            self._bundle.css_errors.append(error)
            return ""
        # Compare on the stripped forms — the value actually returned. The guard
        # used to test the RAW ``out``, so an rtlcss result of pure whitespace
        # (``"\n"``) read as truthy, skipped this branch, and shipped ``""``
        # silently with no banner; stripping ``source`` too keeps a
        # whitespace-only payload (legitimately empty output) from tripping a
        # false positive.
        out = out.strip()
        if source.strip() and not out:
            # Zero exit but empty output for a non-empty payload — rtlcss
            # swallowed the stylesheet without reporting an error.
            error = "rtlcss: error processing payload\n"
            _logger.warning("%s", error)
            self._bundle.css_errors.append(error)
            return ""
        return out

    def _format_compiler_error(self, stderr: str) -> str:
        """Clean up and contextualize a CSS compiler error message.

        Strips Dart Sass noise ("Load paths", "--trace" hints) and appends
        the bundle name and list of preprocessed source files.
        """
        bundle = self._bundle
        error = stderr.split("Load paths", maxsplit=1)[0].replace(
            "  Use --trace for backtrace.", ""
        )
        error += f"This error occurred while compiling the bundle {bundle.name!r} containing:"
        for asset in bundle.stylesheets:
            if isinstance(asset, PreprocessedCSS):
                error += f"\n    - {asset.url or '<inline sass>'}"
        return error

    @classmethod
    def _render_css_error_banner(
        cls, css_errors: Sequence[str], previous_css: str
    ) -> str:
        """Build the degraded-CSS payload shown when a stylesheet fails to compile.

        Re-serves the last good CSS (``previous_css``) plus a red banner naming
        the error. Idempotent across repeated failures: any banner already in
        ``previous_css`` is stripped (split on :attr:`_CSS_ERROR_HEADER`) before
        a fresh one is appended, so the banners never stack. ``css_errors`` text
        is escaped for a CSS string literal (``\\`` → ``\\\\`` FIRST, then ``"`` →
        ``\\"``, newline → ``\\A``, ``*`` → ``\\*``) so the message cannot break
        out of the ``content:`` value or open a comment. The backslash pass runs
        first so a literal ``\\`` in the error (a Windows path, a regex from Sass)
        becomes ``\\\\`` rather than being read as a CSS escape (``\\f`` etc.) — and
        so it does not double the backslashes the later escapes introduce.

        :param css_errors: per-asset / bundle compile errors, joined newline-wise
        :param previous_css: decoded raw of the last good attachment (``""`` if none)
        :return: the CSS to persist as the degraded bundle
        """
        error_message = (
            "\n".join(css_errors)
            .replace("\\", "\\\\")
            .replace('"', r"\"")
            .replace("\n", r"\A")
            .replace("*", r"\*")
        )
        carried_over = previous_css.split(cls._CSS_ERROR_HEADER, maxsplit=1)[0]
        banner = f"""
body::before {{
  font-weight: bold;
  content: "A css error occurred, using an old style to render this page";
  position: fixed;
  left: 0;
  bottom: 0;
  z-index: 100000000000;
  background-color: #C00;
  color: #DDD;
}}

css_error_message {{
  content: "{error_message}";
}}
"""
        return cls._CSS_ERROR_HEADER.join([carried_over, banner])


class XmlTemplatePipeline:
    """Render one bundle's OWL templates into the JS that registers them.

    Split out of :class:`AssetsBundle` so all template handling lives behind one
    boundary, mirroring :class:`CssPipeline` for stylesheets: parsing into
    primary/extension blocks (:meth:`xml`), rendering the ``registerTemplate``
    calls (:meth:`generate_xml_bundle`), and the two delivery wrappers — the
    legacy classic-bundle IIFE (:meth:`legacy_template_iife`) and the ESM
    ``<script type="module">`` form (:meth:`generate_esm_template_bundle`).
    ``AssetsBundle`` keeps thin façades for its public/test surface and the
    ``ir_qweb`` call sites.
    """

    # OWL template-registration API destructured from ``@web/core/templates`` by
    # the generated template bundles. Three call sites consume this exact set —
    # the legacy IIFE wrapper and both header forms of
    # ``generate_esm_template_bundle`` — so a single source keeps them from
    # drifting when a registrar is added or renamed.
    _TEMPLATE_MODULE = "@web/core/templates"
    _TEMPLATE_REGISTRARS = (
        "checkPrimaryTemplateParents, registerTemplate, registerTemplateExtension"
    )

    def __init__(self, bundle: AssetsBundle) -> None:
        """Bind the pipeline to the bundle whose templates it renders."""
        self._bundle = bundle

    def xml(self) -> list[XMLBlock]:
        """
        Create a list of blocks. A block can have one of the two types "templates" or "extensions".
        A template with no parent or template with t-inherit-mode="primary" goes in a block of type "templates".
        A template with t-inherit-mode="extension" goes in a block of type "extensions".

        Used parsed attributes:
        * `t-name`: template name
        * `t-inherit`: inherited template name.
        * 't-inherit-mode':  'primary' or 'extension'.

        :return: a list of blocks
        """
        bundle = self._bundle
        blocks = []
        block = None
        for asset in bundle.templates:
            # ``template_elements`` parses each asset's XML once and caches it
            # (see XMLAsset); a parse error surfaces as XMLAssetError at access
            # time and is handled by generate_xml_bundle's try/except.
            for template_tree in asset.template_elements:
                template_name = template_tree.get("t-name")
                inherit_from = template_tree.get("t-inherit")
                inherit_mode = None
                if inherit_from:
                    inherit_mode = template_tree.get("t-inherit-mode", "primary")
                    if inherit_mode not in {"primary", "extension"}:
                        # ``asset.name`` covers inline assets (url is None),
                        # where ``url.split`` would crash the error path.
                        addon = asset.url.split("/")[1] if asset.url else asset.name
                        raise asset._error(
                            bundle.env._(
                                'Invalid inherit mode. Module "%(module)s" and template name "%(template_name)s"',
                                module=addon,
                                template_name=template_name,
                            )
                        )
                if inherit_mode == "extension":
                    if block is None or block["type"] != "extensions":
                        block = {
                            "type": "extensions",
                            "extensions": {},
                        }
                        blocks.append(block)
                    block["extensions"].setdefault(inherit_from, [])
                    block["extensions"][inherit_from].append((template_tree, asset.url))
                elif template_name:
                    if block is None or block["type"] != "templates":
                        block = {"type": "templates", "templates": []}
                        blocks.append(block)
                    block["templates"].append((template_tree, asset.url, inherit_from))
                else:
                    raise asset._error(bundle.env._("Template name is missing."))
        return blocks

    def generate_xml_bundle(self) -> str:
        """Render the JS that registers this bundle's XML templates at runtime."""
        content = []
        blocks = []
        try:
            blocks = self.xml()
        except XMLAssetError as e:
            content.append(f"throw new Error({json.dumps(str(e))});")

        def get_template(element: etree._Element) -> str:
            element.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            string = etree.tostring(element, encoding="unicode")
            return (
                string.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            )

        names = OrderedSet()
        primary_parents = OrderedSet()
        extension_parents = OrderedSet()
        for block in blocks:
            if block["type"] == "templates":
                for element, url, inherit_from in block["templates"]:
                    if inherit_from:
                        primary_parents.add(inherit_from)
                    name = element.get("t-name")
                    names.add(name)
                    template = get_template(element)
                    # The URL is a JS string argument, not template-literal
                    # text: json.dumps quotes/escapes it so a url containing a
                    # backtick or ``${`` cannot break out of (or interpolate
                    # into) the surrounding literal. The template body stays a
                    # backtick literal — get_template already escapes it.
                    content.append(
                        f"registerTemplate({json.dumps(name)}, {json.dumps(url)}, `{template}`);"
                    )
            else:
                for inherit_from, elements in block["extensions"].items():
                    extension_parents.add(inherit_from)
                    for element, url in elements:
                        template = get_template(element)
                        content.append(
                            f"registerTemplateExtension({json.dumps(inherit_from)}, {json.dumps(url)}, `{template}`);"
                        )

        missing_names_for_primary = primary_parents - names
        if missing_names_for_primary:
            content.append(
                f"checkPrimaryTemplateParents({json.dumps(list(missing_names_for_primary))});"
            )
        missing_names_for_extension = extension_parents - names
        if missing_names_for_extension:
            missing_msg = "Missing (extension) parent templates: " + ", ".join(
                missing_names_for_extension
            )
            content.append(f"console.error({json.dumps(missing_msg)});")

        return "\n".join(content)

    def generate_esm_template_bundle(self, use_import=True) -> str:
        """Generate an ESM template bundle for ``<script type="module">``.

        When *use_import* is True (debug mode), uses native ``import``
        from ``@web/core/templates`` (resolved via import map).

        When False (production esbuild), accesses the templates module
        via ``odoo.loader.modules.get()`` — this avoids a second module
        instance (esbuild internalizes @web/core/templates, so an
        ``import`` would create a separate copy with its own registry).
        The esbuild bundle must execute first (registerNativeModules).
        """
        bundle = self._bundle
        if not bundle.templates:
            return ""
        templates = self.generate_xml_bundle()
        if not templates:
            return ""
        if use_import:
            header = (
                f"import {{ {self._TEMPLATE_REGISTRARS} }} "
                f'from "{self._TEMPLATE_MODULE}";\n'
            )
        else:
            header = (
                f"const {{ {self._TEMPLATE_REGISTRARS} }} = "
                f'odoo.loader.modules.get("{self._TEMPLATE_MODULE}");\n'
            )
        return f"{header}/* {bundle.name} */\n{templates}\n"

    def legacy_template_iife(self) -> str:
        """Wrap the registered templates in the classic-bundle IIFE.

        Non-ESM bundles ship their templates *inside* the concatenated
        ``.min.js`` via this wrapper; ESM bundles use
        :meth:`generate_esm_template_bundle` instead.
        """
        templates = self.generate_xml_bundle()
        return textwrap.dedent(f"""

            /*******************************************
            *  Templates                               *
            *******************************************/

            (function() {{
                "use strict";
                const {{ {self._TEMPLATE_REGISTRARS} }} = odoo.loader.modules.get("{self._TEMPLATE_MODULE}");
                /* {self._bundle.name} */
                {templates}
            }})();
        """)


class JsPipeline:
    """Assemble one bundle's JavaScript content for the legacy concatenated bundle.

    Split out of :class:`AssetsBundle` so JS *content generation* — the
    module-syntax guard, the production concatenation, and the debug sourcemap
    body — lives behind one boundary, mirroring :class:`CssPipeline`. Attachment
    persistence (the ``js`` / ``js.map`` records) stays on :class:`AssetsBundle`
    (:meth:`AssetsBundle.js` / :meth:`AssetsBundle.js_with_sourcemap`), which
    orchestrates this pipeline together with :class:`AssetAttachmentStore` — the
    same division of labour the CSS path uses.
    """

    def __init__(self, bundle: AssetsBundle) -> None:
        """Bind the pipeline to the bundle whose JavaScript it assembles."""
        self._bundle = bundle

    def _module_syntax_error_stub(self, asset: JavascriptAsset) -> str | None:
        """Return a ``console.error`` stub when module syntax can't be concatenated.

        :param asset: legacy-routed JS asset about to be concatenated
        :return: replacement JS for the asset, or ``None`` when it is safe
        :rtype: str | None
        """
        # Since the legacy transpiler was removed, ES-module syntax inside the
        # concatenated classic bundle is a browser-side SyntaxError that takes
        # the WHOLE bundle down. Excluding the file keeps the rest functional
        # and the misconfiguration loud on both server and client.  Detection
        # is syntax-based on purpose: the ``is_odoo_module`` routing heuristic
        # also claims plain non-module files under /static/src, which are
        # perfectly valid in a classic script and must not be stubbed.
        bundle = self._bundle
        if bundle._is_esm_bundle:
            return None
        header = asset.parsed_header
        if header and header["ignore"]:
            # ``@odoo-module ignore`` is an explicit opt-out: the author
            # asserts the file is classic-script safe.
            return None
        if not header and not has_module_syntax(asset.raw_content):
            return None
        msg = (
            f"Module-syntax file {asset.url or asset.name!r} cannot be "
            f"concatenated into non-ESM bundle {bundle.name!r}; declare the "
            "bundle under the 'esm' key of its module's manifest to serve "
            "it. File skipped."
        )
        log_event(
            _bundle_log,
            logging.ERROR,
            "module_syntax_in_legacy_bundle",
            bundle=bundle.name,
            url=asset.url or "<inline>",
        )
        return f"console.error({json.dumps(msg)});"

    def minified_bundle(self, template_bundle: str) -> str:
        """Concatenated, minified JS for the production (``min.js``) bundle.

        ``template_bundle`` is the legacy template IIFE appended verbatim (empty
        for ESM bundles, which deliver templates separately).
        """
        content_bundle = ";\n".join(
            self._module_syntax_error_stub(asset) or asset.minify()
            for asset in self._bundle.javascripts
        )
        return content_bundle + template_bundle

    def sourcemap_bundle(
        self, generator: SourceMapGenerator, sourcemap_url: str, template_bundle: str
    ) -> str:
        """Build the un-minified debug JS body, populating *generator*.

        Adds a per-file source mapping to *generator* and appends the
        ``sourceMappingURL`` link. The caller owns the ``js`` / ``js.map``
        attachment I/O (and sets ``generator.file`` once the js URL is known).
        """
        content_bundle_list = []
        content_line_count = 0
        # Lines emitted before the file body by ``with_header(minimal=False)``;
        # the verbose header and this offset are kept in sync through the
        # ``JavascriptAsset._HEADER_LINE_COUNT`` constant.
        line_header = JavascriptAsset._HEADER_LINE_COUNT
        for asset in self._bundle.javascripts:
            stub = self._module_syntax_error_stub(asset)
            if stub:
                # Excluded from the sourcemap too — the stub replaces the
                # file body, so mapped positions would be meaningless.
                content_bundle_list.append(stub)
                content_line_count += stub.count("\n") + 1
                continue
            generator.add_source(
                asset.url,
                asset.content,
                content_line_count,
                start_offset=line_header,
            )

            content_bundle_list.append(asset.with_header(asset.content, minimal=False))
            content_line_count += asset.content.count("\n") + 1 + line_header

        content_bundle = ";\n".join(content_bundle_list)
        if template_bundle:
            content_bundle += template_bundle

        content_bundle += "\n\n//# sourceMappingURL=" + sourcemap_url
        return content_bundle


class AssetsBundle:
    """Compile, version and persist the JS/CSS/XML assets of one named bundle."""

    # @import matcher used by ``css()`` / ``css_with_sourcemap`` to hoist and
    # comment @import rules. The stylesheet preprocessor's own import sanitizer
    # and split-marker regexes live on :class:`CssPipeline`.
    rx_css_import = re.compile(r"(@import[^;{]+;?)", re.MULTILINE)

    # Source extensions the ``__init__`` file loop has a case-arm for.
    # Anything else is a misconfiguration tripwire (see the loop), NOT a
    # flag-based drop (css-only / js-only construction is normal).
    # Indented-syntax ``.sass`` is NOT supported: the compiler is always
    # invoked with ``syntax="scss"``, so a ``.sass`` file would die with a
    # misleading SCSS parse error — let the tripwire flag it instead.
    _BUNDLE_FILE_EXTENSIONS = frozenset({"scss", "css", "js", "xml"})

    # ─────────────────────────────────────────────────────────────────
    # ESM bundle classification
    # ─────────────────────────────────────────────────────────────────
    #
    # Which bundles are esbuild-compiled — and their parent/child
    # relationships (dynamic lazy children, import-map satellites) — is
    # DECLARATIVE: each module lists its own bundles under the ``esm``
    # key of its ``__manifest__.py``.  The aggregate is built and
    # validated by ``odoo.tools.assets.esm_registry.esm_registry()`` (see its
    # module docstring for the schema and the three relationship axes)
    # and invalidated alongside the esbuild addon scan below.

    @classmethod
    def _validate_external_libs(cls, import_map_keys: set[str]) -> None:
        """Cross-check ``ODOO_EXTERNAL_LIBS`` against the esbuild alias list.

        Fails fast at server startup if the two declaration sites drift
        apart in a way that would break production builds.  The check
        raises on one invariant only:

        * Every ``ODOO_EXTERNAL_LIBS`` entry must have a matching
          esbuild resolution (:meth:`EsbuildCompiler.resolves_specifier`:
          a per-lib alias or pattern-level external coverage).  Otherwise
          esbuild fails to resolve the specifier during production
          bundling.

        The reverse direction is asymmetric and intentionally NOT
        enforced: ``_LIB_CANDIDATES`` entries exist for esbuild to
        INLINE (e.g. ``luxon`` adapter, ``@odoo/o-spreadsheet``), so
        they don't need import-map entries in production.  Debug-mode
        consumers of those specifiers are expected to inject their own
        import-map entry or avoid bare imports — Enterprise handles
        this via its own pragma/transform layer.

        :param import_map_keys: the import-map specifiers to validate —
            ``set(ODOO_EXTERNAL_LIBS)`` at module load; tests pass
            fabricated sets.
        """
        missing_alias = [
            spec
            for spec in import_map_keys
            if not EsbuildCompiler.resolves_specifier(spec)
        ]
        if missing_alias:
            raise ValueError(
                f"ODOO_EXTERNAL_LIBS declares {sorted(missing_alias)} "
                f"but esbuild has no resolution for them (no per-lib alias, "
                f"no pattern-level external coverage). Production builds "
                f"will fail to resolve these specifiers.",
            )

    def __init__(
        self,
        name: str,
        files: list[BundleFileSpec],
        external_assets: Sequence[str] = (),
        *,
        env: Environment,
        css: bool = True,
        js: bool = True,
        debug_assets: bool = False,
        rtl: bool = False,
        assets_params: dict[str, Any] | None = None,
        autoprefix: bool = False,
    ) -> None:
        """
        :param name: bundle name
        :param files: files to be added to the bundle
        :param env: the environment the bundle reads and persists through
            (required — the old ``request.env`` fallback hid a global)
        :param css: if css is True, the stylesheets files are added to the bundle
        :param js: if js is True, the javascript files are added to the bundle
        """
        self.name = name
        self.env = env
        self.javascripts = []
        self.native_modules = []
        self._is_esm_bundle = name in esm_registry().bundles
        self.templates = []
        self.stylesheets = []
        self.css_errors = []
        # Snapshot of the input file specs; read by the content-invalidation
        # test suite to assert the file list changed across rebuilds.
        self.files = files
        self.rtl = rtl
        self.assets_params = assets_params or {}
        self.autoprefix = autoprefix
        self.has_css = css
        self.has_js = js
        self._checksum_cache = {}
        self.is_debug_assets = debug_assets
        self.external_assets = []
        for url in external_assets:
            # Strip query string / fragment before the extension probe so a
            # CDN URL like ``…/style.css?v=2`` is not silently discarded.
            ext = url.partition("#")[0].partition("?")[0].rpartition(".")[2]
            if (css and ext in STYLE_EXTENSIONS) or (js and ext in SCRIPT_EXTENSIONS):
                self.external_assets.append(url)
            elif ext not in STYLE_EXTENSIONS and ext not in SCRIPT_EXTENSIONS:
                # Flag-based drops (css-only or js-only construction) are
                # normal; an unrecognized extension is a misconfiguration
                # that previously vanished without a trace.
                log_event(
                    _bundle_log,
                    logging.WARNING,
                    "external_asset_skipped",
                    bundle=name,
                    url=url,
                )

        # asset-wide html "media" attribute
        for f in files:
            extension = f["url"].rpartition(".")[2]
            params = {
                "url": f["url"],
                "filename": f["filename"],
                "inline": f["content"],
                "last_modified": (
                    None if self.is_debug_assets else f.get("last_modified")
                ),
            }
            if css:
                css_params = {
                    "rtl": self.rtl,
                    "autoprefix": self.autoprefix,
                }
                match extension:
                    case "scss":
                        self.stylesheets.append(
                            ScssStylesheetAsset(self, **params, **css_params)
                        )
                    case "css":
                        self.stylesheets.append(
                            StylesheetAsset(self, **params, **css_params)
                        )
            if js:
                match extension:
                    case "js":
                        asset = JavascriptAsset(self, **params)
                        if self._is_esm_bundle and self._is_module_js(asset):
                            # ALL ES module files (native + legacy @odoo-module)
                            # go through esbuild. Legacy @odoo-module files use
                            # the same import/export syntax — esbuild handles both.
                            self.native_modules.append(asset)
                        else:
                            self.javascripts.append(asset)
                    case "xml":
                        self.templates.append(XMLAsset(self, **params))
            if extension not in self._BUNDLE_FILE_EXTENSIONS:
                # No case-arm recognizes this extension, so the file was
                # dropped — previously without a trace (the external-asset
                # filter above got its tripwire in an earlier round; the
                # internal file list deserves the same).
                log_event(
                    _bundle_log,
                    logging.WARNING,
                    "bundle_file_skipped",
                    bundle=name,
                    url=f["url"],
                )

        # Version snapshot — pin the assets the bundle checksum (and thus the
        # served URL) is computed from, captured here before any compilation
        # mutates the live lists.  ``preprocess_css`` inserts a derived
        # ``@at-rules`` StylesheetAsset into ``self.stylesheets`` for content
        # assembly; that fragment is compiler output, not a source file, and
        # must not perturb the version.  Snapshotting at construction makes
        # ``get_checksum`` independent of whether ``get_version`` runs before
        # or after ``preprocess_css`` — replacing the ordering invariant that
        # used to live as a comment in ``preprocess_css``.
        self._version_assets = {
            "css": tuple(self.stylesheets),
            "js": tuple(self.javascripts + self.templates + self.native_modules),
        }

        log_event(
            _bundle_log,
            logging.DEBUG,
            "init",
            bundle=name,
            files=len(files),
            esm=self._is_esm_bundle,
            debug=debug_assets,
            native=len(self.native_modules),
            legacy_js=len(self.javascripts),
            templates=len(self.templates),
            css=len(self.stylesheets),
            external=len(self.external_assets),
        )

    @property
    def _has_legacy_templates(self) -> bool:
        """Whether templates ship *inside* the concatenated legacy JS bundle.

        ESM bundles deliver templates as a separate ``<script type="module">``
        (see :meth:`generate_esm_template_bundle`), so their templates never
        enter the ``.min.js``; only a non-ESM bundle wraps them inline.
        """
        return bool(self.templates and not self._is_esm_bundle)

    @property
    def has_js_content(self) -> bool:
        """Whether :meth:`js` yields a non-empty legacy bundle worth linking.

        The single source of truth for two decisions that must agree: whether
        :meth:`get_links` emits a ``.js`` link, and whether :meth:`js` wraps a
        template block. Encoding the predicate once stops the two from drifting.
        """
        return bool(self.javascripts or self._has_legacy_templates)

    def get_links(self) -> list[str]:
        """Return the list of asset URLs for this bundle.

        Native ESM modules are excluded from the concatenated bundle — they are
        served individually and loaded via import map + ``<script type="module">``.
        Use :meth:`get_native_module_data` to get their URLs and import map entries.
        """
        response = []

        if self.has_css and self.stylesheets:
            response.append(self.get_link("css"))

        if self.has_js and self.has_js_content:
            response.append(self.get_link("js"))

        return self.external_assets + response

    def get_native_module_data(self, with_bridges: bool = True) -> NativeModuleData:
        """Return import map and preload data for native ESM modules.

        Returns a dict with:
        - ``import_map``: ``{specifier: url}`` for the import map
        - ``preload_urls``: URLs for ``<link rel="modulepreload">``
        - ``bridge_import_map``: ``{specifier: shim_url}`` for
          legacy modules that native modules import from

        :param with_bridges: when ``False``, skip building the
            ``odoo.loader.modules`` bridge (``bridge_import_map`` comes back
            empty). Callers that merge only ``import_map`` — the dynamic-child
            and secondary import-map paths in ``ir_qweb`` — pass ``False`` to
            avoid the bridge's regex discovery and attachment persistence,
            work whose result they discard.
        """
        if not self.native_modules:
            log_event(
                _bundle_log,
                logging.DEBUG,
                "native_module_data_empty",
                bundle=self.name,
            )
            return {
                "import_map": {},
                "preload_urls": [],
                "bridge_import_map": {},
            }

        import_map = {}
        preload_urls = []

        def _map(spec: str, url: str, kind: str) -> None:
            # The browser import map holds ONE url per specifier, but two native
            # modules can resolve to the same specifier: ``foo.js`` and
            # ``foo/index.js`` both yield ``@addon/foo`` (url_to_module_path
            # strips ``/index``), and the ``/index`` long form or a declared
            # alias can clash with another module likewise. Keep the existing
            # last-wins behaviour (changing it could move a live bundle's
            # resolution), but make the dropped mapping loud — the same
            # "no silent drops" tripwire the ``__init__`` file loop emits for
            # skipped assets. Same-url re-adds (a module's own spec + long form)
            # are not collisions and stay silent.
            prior = import_map.get(spec)
            if prior is not None and prior != url:
                log_event(
                    _bundle_log,
                    logging.WARNING,
                    "import_map_spec_collision",
                    bundle=self.name,
                    spec=spec,
                    kind=kind,
                    previous=prior,
                    replaced_with=url,
                )
            import_map[spec] = url

        for asset in self.native_modules:
            spec = asset.module_path
            # Use bare URLs without ?v= cache-busting.  Native ESM modules
            # are resolved by the browser's module system — relative imports
            # (e.g. ``./error_dialogs.js``) resolve to bare URLs.  If the
            # import map uses ``?v=`` but relatives don't, the browser treats
            # them as different modules and evaluates the file TWICE, causing
            # duplicate registry errors.  Cache invalidation for native
            # modules relies on the import map script tag changing (which
            # triggers a full page reload via bus.bus bundle_changed).
            _map(spec, asset.url, "module_path")
            preload_urls.append(asset.url)
            # For index.js files, url_to_module_path strips "/index" so
            # "@spreadsheet/global_filters/index" becomes
            # "@spreadsheet/global_filters".  Add an entry for the long
            # form too so `import from "@spreadsheet/global_filters/index"`
            # resolves to the same URL instead of a data: URI bridge.
            if asset.url.endswith("/index.js"):
                _map(spec + "/index", asset.url, "index_long_form")
            # If the module declares an alias (e.g. @odoo/o-spreadsheet),
            # add an import map entry so `import ... from "alias"` resolves
            # to the same URL.
            header = asset.parsed_header
            if header and header["alias"]:
                _map(header["alias"], asset.url, "alias")

        # ``import_map`` keys ARE this bundle's native specifiers — every key
        # added above is the bundle's own module path, "/index" long form, or
        # declared alias.  They double as the "owned by this bundle" set handed
        # to ``_build_native_to_legacy_bridge`` (so it treats them as owned and
        # does not emit a ``data:`` URI shim that would overwrite the direct URL
        # in ``ir_qweb`` bundle assembly).  No parallel accumulator to keep in
        # lockstep, and the set is built only when bridges are actually needed.
        bridge_import_map = (
            self._bridges._build_native_to_legacy_bridge(set(import_map))
            if with_bridges
            else {}
        )
        log_event(
            _bundle_log,
            logging.DEBUG,
            "native_module_data",
            bundle=self.name,
            specs=len(import_map),
            preload=len(preload_urls),
            bridges=len(bridge_import_map),
        )

        return {
            "import_map": import_map,
            "preload_urls": preload_urls,
            "bridge_import_map": bridge_import_map,
        }

    # ── esbuild layer (moved to odoo.tools.assets.esbuild, H2 Phase B) ──
    # Only the production surface remains on this class:
    # ``esbuild_native_bundle`` (the entry ir_qweb calls),
    # ``_get_esbuild_addon_flags`` (the provider seam tests patch here),
    # and ``invalidate_addon_scan_cache`` (called by ir_module's
    # ``update_list``).  Helper-level tests target ``EsbuildCompiler``
    # directly; constant reads (timeouts, target, lib candidates) go to
    # ``EsbuildCompiler`` as well.

    @classmethod
    def invalidate_addon_scan_cache(cls) -> None:
        """Clear the per-process addons-on-disk caches.

        Covers both the esbuild addon-flag scan (see EsbuildCompiler) and
        the manifest-aggregated ESM bundle registry — they share the same
        invalidation trigger (``ir.module.module.update_list``).
        """
        EsbuildCompiler.invalidate_addon_scan_cache()
        invalidate_esm_registry()

    @classmethod
    def _get_esbuild_addon_flags(cls, odoo_root: Path) -> tuple[list, list]:
        """Delegate to the esbuild layer; the per-bundle addon-flags seam.

        ``_make_esbuild_compiler`` hands this callable to ``EsbuildCompiler`` as
        its ``addon_flags_provider``; a test (or override) can patch it here to
        inject fabricated flags. That threading is pinned by
        ``test_review_followup.TestEsbuildCompilerAddonFlagsSeam``.
        """
        return EsbuildCompiler._get_esbuild_addon_flags(odoo_root)

    def _make_esbuild_compiler(self) -> EsbuildCompiler:
        """Build the subprocess-layer compiler from this bundle's state."""
        # Single-use factory (one call per ``esbuild_native_bundle``), hence a
        # method rather than a cached property like ``_store``.  One registry
        # read for both membership checks — it is memoized, but binding it keeps
        # the two derived bundle-name lookups reading the same snapshot.
        registry = esm_registry()
        return EsbuildCompiler(
            self.name,
            self.native_modules,
            self.javascripts,
            import_map_included=self.name in registry.import_map_included_bundles,
            skip_legacy_test_imports=self.name in registry.import_map_includes,
            addon_flags_provider=self._get_esbuild_addon_flags,
        )

    def esbuild_native_bundle(
        self,
        timeout_s: int | None = None,
        target: str | None = None,
        source_maps: str | None = None,
        dynamic_child_specs: frozenset[str] | None = None,
    ) -> EsbuildResult:
        """Bundle native ESM modules into one minified file via esbuild.

        Thin wrapper over :meth:`EsbuildCompiler.compile` (see its docstring
        for the parameters). Returns the compiler's :class:`EsbuildResult`
        verbatim — ``code`` plus the ``metafile`` / ``sourcemap`` that
        ``ir_qweb`` persists as sibling attachments. Returning the whole
        result (rather than stashing the two siblings on ``self`` and handing
        back only ``code``) keeps the build's outputs together and off the
        bundle's instance state.
        """
        return self._make_esbuild_compiler().compile(
            timeout_s=timeout_s,
            target=target,
            source_maps=source_maps,
            dynamic_child_specs=dynamic_child_specs,
        )

    # ── bridge layer (moved to odoo.tools.assets.esm_bridges, H3 split) ──
    # ``_bridges`` is the explicit collaborator: ir_qweb and the test suite
    # call its methods directly (``bundle._bridges.<method>``), mirroring the
    # ``_store`` boundary, so AssetsBundle no longer carries a fan of same-named
    # forwarders. The logic and its persistence policy live in
    # BridgeShimManager; seam-level tests (rw-cursor escalation) patch
    # ``BridgeShimManager._persist_bridges_via_rw_cursor`` directly.

    @functools.cached_property
    def _bridges(self) -> BridgeShimManager:
        """Bridge-shim layer bound to this bundle's env, name and modules.

        Cached: BridgeShimManager is stateless beyond its three inputs (see its
        docstring), and all three — env, name, native_modules — are fixed for
        the bundle's lifetime, so a single instance serves every call.
        """
        return BridgeShimManager(self.env, self.name, self.native_modules)

    # Moved to odoo.tools.assets.esm_graph (H2 split); kept as a staticmethod
    # so internal call sites and the test suite keep their surface.
    _bridge_shim_source = staticmethod(_bridge_shim_source)

    def get_link(self, asset_type: str) -> str:
        """Return the versioned (or ``debug``) URL for this bundle's ``asset_type``."""
        unique = self.get_version(asset_type) if not self.is_debug_assets else "debug"
        extension = asset_type if self.is_debug_assets else f"min.{asset_type}"
        return self.get_asset_url(unique=unique, extension=extension)

    def get_version(self, asset_type: str) -> str:
        """Return the 7-hex version segment embedded in the bundle URL."""
        return self.get_checksum(asset_type)[0:7]

    def get_checksum(self, asset_type: str) -> str:
        """Compute a SHA256 over rendered bundle + linked files last_modified.

        Native ESM modules are included in the JS checksum so that changes
        to any module (legacy or native) invalidate the bundle cache.

        Computed over the ``__init__`` version snapshot (see
        ``self._version_assets``), not the live asset lists, so the version
        is stable regardless of compilation-time mutations.
        """
        if asset_type not in self._checksum_cache:
            if asset_type not in self._version_assets:
                raise ValueError(f"Asset type {asset_type} not known")
            h = hashlib.sha256()
            for asset in self._version_assets[asset_type]:
                h.update(asset.unique_descriptor.encode())
            self._checksum_cache[asset_type] = h.hexdigest()
        return self._checksum_cache[asset_type]

    # ── attachment persistence (extracted to AssetAttachmentStore) ──
    # Thin delegators keep the historical/test surface and let the content
    # pipeline (``js``/``css``/sourcemaps) keep calling ``self.<method>``; the
    # raw SQL and its concurrency handling live in AssetAttachmentStore.
    # Seam tests patch ``AssetAttachmentStore._unlink_attachments`` directly.

    @functools.cached_property
    def _store(self) -> AssetAttachmentStore:
        """Attachment persistence layer for this bundle, built once.

        ``version_provider=self.get_version`` breaks the bundle↔store cycle:
        the store reads the version on demand without owning checksum state.
        """
        return AssetAttachmentStore(
            self.env,
            self.name,
            assets_params=self.assets_params,
            rtl=self.rtl,
            autoprefix=self.autoprefix,
            version_provider=self.get_version,
        )

    def get_asset_url(self, unique: str, extension: str) -> str:
        """Delegates to :meth:`AssetAttachmentStore.get_asset_url`."""
        return self._store.get_asset_url(unique, extension)

    def get_attachments(
        self, extension: str, ignore_version: bool = False
    ) -> IrAttachment:
        """Delegates to :meth:`AssetAttachmentStore.get_attachments`."""
        return self._store.get_attachments(extension, ignore_version)

    def save_attachment(self, extension: str, content: str) -> IrAttachment:
        """Delegates to :meth:`AssetAttachmentStore.save_attachment`."""
        return self._store.save_attachment(extension, content)

    def _is_module_js(self, asset: JavascriptAsset) -> bool:
        """Whether ``asset`` is routed through the ESM pipeline.

        File-backed assets go through the process-level classification cache;
        inline assets (no filename) are probed directly.
        """
        if asset._filename:
            return _cached_module_classification(
                asset.url or "",
                asset._filename,
                asset.last_modified,
            )
        return asset.is_native or is_odoo_module(asset.url or "", asset.raw_content)

    @functools.cached_property
    def _js(self) -> JsPipeline:
        """JS content-assembly pipeline bound to this bundle, built once.

        Owns the legacy concatenation, the module-syntax guard and the debug
        sourcemap body; ``js`` / ``js_with_sourcemap`` below keep the attachment
        I/O. Mirrors :attr:`_css`.
        """
        return JsPipeline(self)

    @functools.cached_property
    def _xmltemplates(self) -> XmlTemplatePipeline:
        """OWL-template rendering pipeline bound to this bundle, built once.

        Owns ``xml`` / ``generate_xml_bundle`` and the delivery wrappers; the
        methods below stay as thin façades for the public/test surface and the
        ``ir_qweb`` call sites. Mirrors :attr:`_css`.
        """
        return XmlTemplatePipeline(self)

    def js(self) -> IrAttachment:
        """Return (generating and persisting if needed) the bundle's JS attachment."""
        is_minified = not self.is_debug_assets
        extension = "min.js" if is_minified else "js"
        js_attachment = self.get_attachments(extension)

        if not js_attachment:
            # Non-ESM bundles wrap their templates in the classic IIFE inside the
            # concatenated bundle; ESM bundles (including dynamic) deliver them
            # as a separate <script type="module"> — see
            # _get_native_module_nodes() and generate_esm_template_bundle().
            template_bundle = (
                self._xmltemplates.legacy_template_iife()
                if self._has_legacy_templates
                else ""
            )
            if is_minified:
                content_bundle = self._js.minified_bundle(template_bundle)
                js_attachment = self.save_attachment(extension, content_bundle)
            else:
                js_attachment = self.js_with_sourcemap(template_bundle=template_bundle)

        return js_attachment[0]

    def js_with_sourcemap(self, template_bundle: str | None = None) -> IrAttachment:
        """Create the ir.attachment for the un-minified JS bundle and
        create/modify the ir.attachment for the linked sourcemap.

        :return: the ir.attachment for the un-minified JS bundle
        """
        sourcemap_attachment = self.get_attachments("js.map") or self.save_attachment(
            "js.map", ""
        )
        generator = SourceMapGenerator(
            source_root=_sourcemap_source_root(self.get_asset_url("debug", "js")),
        )
        content_bundle = self._js.sourcemap_bundle(
            generator, sourcemap_attachment.url, template_bundle or ""
        )
        js_attachment = self.save_attachment("js", content_bundle)

        generator.file = js_attachment.url
        sourcemap_attachment.write({"raw": generator.get_content()})

        return js_attachment

    def xml(self) -> list[XMLBlock]:
        """Delegates to :meth:`XmlTemplatePipeline.xml`."""
        return self._xmltemplates.xml()

    def generate_xml_bundle(self) -> str:
        """Delegates to :meth:`XmlTemplatePipeline.generate_xml_bundle`."""
        return self._xmltemplates.generate_xml_bundle()

    def generate_esm_template_bundle(self, use_import=True) -> str:
        """Delegates to :meth:`XmlTemplatePipeline.generate_esm_template_bundle`."""
        return self._xmltemplates.generate_esm_template_bundle(use_import)

    @classmethod
    def _render_css_error_banner(
        cls, css_errors: Sequence[str], previous_css: str
    ) -> str:
        """Delegates to :meth:`CssPipeline._render_css_error_banner`."""
        return CssPipeline._render_css_error_banner(css_errors, previous_css)

    def css(self) -> IrAttachment:
        """Return (generating and persisting if needed) the bundle's CSS attachment.

        Always a singleton record, mirroring :meth:`js` — callers read
        ``.id`` / ``.raw`` directly.
        """
        is_minified = not self.is_debug_assets
        extension = "min.css" if is_minified else "css"
        attachments = self.get_attachments(extension)
        if attachments:
            return attachments[0]

        css = self.preprocess_css()
        if self.css_errors:
            previous_attachment = self.get_attachments(extension, ignore_version=True)
            previous_css = (
                previous_attachment.raw.decode() if previous_attachment else ""
            )
            banner = self._render_css_error_banner(self.css_errors, previous_css)
            return self.save_attachment(extension, banner)

        # Extract @import rules (they must appear at the top of the bundle).
        # String-aware: an ``@import`` written inside a ``content: "…"`` value
        # is neither hoisted nor stripped (see _rewrite_css_outside_strings).
        import_rules: list[str] = []

        def _hoist_import(match: re.Match) -> str:
            import_rules.append(match.group(0))
            return ""

        css = _rewrite_css_outside_strings(self.rx_css_import, _hoist_import, css)

        if is_minified:
            # Move all @import rules to the top
            return self.save_attachment(extension, "\n".join(import_rules + [css]))
        return self.css_with_sourcemap("\n".join(import_rules))

    def css_with_sourcemap(self, content_import_rules: str) -> IrAttachment:
        """Create the ir.attachment for the un-minified CSS bundle and
        create/modify the ir.attachment for the linked sourcemap.

        :param content_import_rules: string containing all the @import rules to put at the beginning of the bundle
        :return: the ir.attachment for the un-minified CSS bundle
        """
        sourcemap_attachment = self.get_attachments("css.map") or self.save_attachment(
            "css.map", ""
        )
        generator = SourceMapGenerator(
            source_root=_sourcemap_source_root(self.get_asset_url("debug", "css")),
        )

        # adds the @import rules at the beginning of the bundle
        content_bundle_list = [content_import_rules]
        content_line_count = content_import_rules.count("\n") + 1
        # Iterate the pipeline's assembled render list (the optional @at-rules
        # fragment + the bundle's stylesheets with their compiled content),
        # populated by the ``preprocess_css`` call ``css()`` made just above.
        # Reading it here — rather than a mutated ``self.stylesheets`` — is what
        # lets preprocess leave the source list untouched.
        for asset in self._css._rendered_assets:
            if asset.content:
                content = asset.with_header(asset.content)
                if asset.url:
                    generator.add_source(asset.url, content, content_line_count)
                # comments all @import rules that have been added at the
                # beginning of the bundle (string-aware: an ``@import`` inside a
                # ``content: "…"`` value is left intact, not commented out)
                content = _rewrite_css_outside_strings(
                    self.rx_css_import,
                    lambda matchobj: f"/* {matchobj.group(0)} */",
                    content,
                )
                content_bundle_list.append(content)
                content_line_count += content.count("\n") + 1

        content_bundle = (
            "\n".join(content_bundle_list)
            + f"\n/*# sourceMappingURL={sourcemap_attachment.url} */"
        )
        css_attachment = self.save_attachment("css", content_bundle)

        generator.file = css_attachment.url
        sourcemap_attachment.write(
            {
                "raw": generator.get_content(),
            }
        )

        return css_attachment

    @functools.cached_property
    def _css(self) -> CssPipeline:
        """CSS preprocessor pipeline bound to this bundle, built once.

        The pipeline reads this bundle's ``stylesheets`` and rebuilds
        ``css_errors`` (see :class:`CssPipeline`); it assembles the rendered
        output into its own ``_rendered_assets`` rather than mutating the
        bundle's source list, and ``css_with_sourcemap`` reads that back. A
        single instance per bundle keeps the render list available across the
        ``preprocess`` → ``css_with_sourcemap`` call sequence.
        """
        return CssPipeline(self)

    def preprocess_css(self) -> str:
        """Delegates to :meth:`CssPipeline.preprocess`."""
        return self._css.preprocess()

    def compile_css(self, compiler: Callable[[str], str], source: str) -> str:
        """Delegates to :meth:`CssPipeline.compile_css`."""
        return self._css.compile_css(compiler, source)

    def run_rtlcss(self, source: str) -> str:
        """Delegates to :meth:`CssPipeline.run_rtlcss`."""
        return self._css.run_rtlcss(source)


class WebAsset:
    """Base class for all asset types (JS, CSS, XML)."""

    def __init__(
        self,
        bundle: AssetsBundle,
        inline: str | None = None,
        url: str | None = None,
        filename: str | None = None,
        last_modified: float | None = None,
    ) -> None:
        self.bundle = bundle
        self.inline = inline
        self.url = url
        self._filename = filename
        self._content: str | None = None
        self._ir_attach: IrAttachment | None = None
        self._last_modified = last_modified
        if not inline and not url:
            raise ValueError(
                f"An asset should either be inlined or url linked, defined in bundle {bundle.name!r}"
            )

    def generate_error(self, msg: str) -> str:
        """Log and return an error message contextualized with the asset URL."""
        msg = f"{msg!r} in file {self.url!r}"
        _logger.error(msg)
        return msg

    @functools.cached_property
    def id(self) -> str:
        return str(uuid.uuid4())

    @functools.cached_property
    def unique_descriptor(self) -> str:
        return f"{self.url or self.inline},{self.last_modified}"

    @functools.cached_property
    def name(self) -> str:
        return "<inline asset>" if self.inline else self.url

    def _resolve_attachment(self) -> None:
        """Resolve a url-only asset to its backing ``ir.attachment`` record.

        No-op for inline or file-backed assets; raises
        ``AssetNotFoundError`` when no attachment serves the URL.
        """
        if not (self.inline or self._filename or self._ir_attach):
            try:
                # Test url against ir.attachments
                self._ir_attach = (
                    self.bundle.env["ir.attachment"]
                    .sudo()
                    ._get_serve_attachment(self.url)
                )
                self._ir_attach.ensure_one()
            except ValueError:
                raise AssetNotFoundError(f"Could not find {self.name}") from None

    @property
    def last_modified(self) -> float | int:
        if self._last_modified is None:
            # Only the expected "asset has no backing attachment" failure is
            # ignored; a real DB error must propagate, not become ``-1``.
            with suppress(AssetNotFoundError):
                self._resolve_attachment()
            if self._filename:
                # debug=assets constructs assets without a build-time mtime
                # so each render re-stats. The same path now also covers a
                # caller that omits ``last_modified`` for a file-backed
                # asset — previously that froze the checksum on a ``-1``
                # sentinel and file edits stopped invalidating the bundle.
                with suppress(OSError):
                    self._last_modified = Path(self._filename).stat().st_mtime
            elif self._ir_attach:
                self._last_modified = self._ir_attach.write_date.replace(
                    tzinfo=UTC
                ).timestamp()
            if self._last_modified is None:
                # ``is None``, not falsy: an epoch mtime (0.0) is a real
                # timestamp and must not collapse into the sentinel.
                self._last_modified = -1
        return self._last_modified

    @property
    def content(self) -> str:
        if self._content is None:
            self._content = self.inline or self._fetch_content()
        return self._content

    def _fetch_content(self) -> str:
        """Fetch content from file or database."""
        try:
            self._resolve_attachment()
            if self._filename:
                with file_open(self._filename, "rb", filter_ext=EXTENSIONS) as fp:
                    return fp.read().decode("utf-8")
            else:
                return self._ir_attach.raw.decode()
        except UnicodeDecodeError:
            raise AssetError(f"{self.name} is not utf-8 encoded.") from None
        except OSError:
            raise AssetNotFoundError(f"File {self.name} does not exist.") from None
        except AssetError:
            # Already contextualized (e.g. ``AssetNotFoundError`` from
            # ``_resolve_attachment``); re-wrapping would erase the subclass.
            raise
        except ValueError as e:
            # ``file_open(filter_ext=...)`` rejecting the extension.
            raise AssetError(f"Could not get content for {self.name}.") from e

    def minify(self) -> str:
        """Return this asset's bundle-ready fragment.

        Subclasses compress the content and prepend the per-file header;
        the base implementation passes the content through untouched.
        """
        return self.content

    def with_header(self, content: str | None = None) -> str:
        if content is None:
            content = self.content
        return f"\n/* {self.name} */\n{content}"


class JavascriptAsset(WebAsset):
    """JS file asset: legacy concatenation member or native-ESM module."""

    # Number of lines ``with_header(minimal=False)`` emits BEFORE the file
    # body (blank line + top border + 2 info lines + bottom border).
    # ``AssetsBundle.js_with_sourcemap`` feeds this to the sourcemap
    # generator as ``start_offset`` so emitted line numbers line up with the
    # bundled output. Keep in sync with ``with_header`` if the header shape
    # changes — ``test_js_header_line_count`` guards the coupling.
    _HEADER_LINE_COUNT = 5

    @functools.cached_property
    def parsed_header(self) -> re.Match[str] | None:
        """Parsed ``@odoo-module`` header match (cached), or ``None``.

        The header regex is consulted at several points in the bundle
        lifecycle (native/legacy classification, import-map alias, esbuild
        alias flags); caching it parses the file's first 500 chars once and
        keeps those call sites from drifting.
        """
        return _parse_odoo_module_header(self.raw_content)

    def generate_error(self, msg: str) -> str:
        msg = super().generate_error(msg)
        return f"console.error({json.dumps(msg)});"

    @functools.cached_property
    def is_native(self) -> bool:
        """Whether this file uses ``@odoo-module native`` (browser-native ESM)."""
        header = self.parsed_header
        return bool(header and header["native"])

    @functools.cached_property
    def module_path(self) -> str:
        """The ``@module/path`` identifier (e.g. ``@web/core/registry``).

        Cached — a pure function of the (immutable) ``self.url`` read several
        times per module across the import map, the esbuild entry, and both
        bridge builders; recomputing ``url_to_module_path`` (a regex match) on
        every access was pure overhead.
        """
        return url_to_module_path(self.url)

    @property
    def raw_content(self) -> str:
        """The file's source (cached by ``WebAsset``).

        Public alias of :attr:`content` kept for the call sites that read a
        JS asset's source explicitly (``ir_qweb``, the bridge builders). For
        JS the two are identical — there is no transpilation step — so
        ``content`` inherits ``WebAsset.content`` rather than
        round-tripping through this property.
        """
        return super().content

    def minify(self) -> str:
        content = self.content
        # rjsmin (1.2.5) handles top-level template literals fine but corrupts
        # NESTED ones (whitespace inside a template-in-``${}`` collapses). A
        # nested literal REQUIRES an interpolation, so a file with backticks but
        # no ``${`` cannot trip the bug — minify it in-process with rjsmin
        # instead of paying an esbuild subprocess. Only ``${``-bearing backtick
        # files are sent to esbuild (a conservative superset: a non-nested
        # ``${}`` is safe in rjsmin too, but it is cheap to over-include and
        # keeps the gate purely textual). On esbuild failure the file ships
        # unminified — the previous behaviour for every backtick file.
        if "`" not in content or "${" not in content:
            return self.with_header(rjsmin(content, keep_bang_comments=True))
        minified = minify_js(content, label=self.url or self.name)
        return self.with_header(minified if minified is not None else content)

    def _fetch_content(self) -> str:
        try:
            return super()._fetch_content()
        except AssetError as e:
            return self.generate_error(str(e))

    def with_header(self, content: str | None = None, minimal: bool = True) -> str:
        if minimal:
            return super().with_header(content)

        # Verbose header — _HEADER_LINE_COUNT (5) lines before the body,
        # consumed by AssetsBundle.js_with_sourcemap as the sourcemap offset:
        #   <blank>
        #   /**************************
        #   *  Filepath: <asset_url>  *
        #   *  Lines: 42              *
        #   **************************/
        line_count = content.count("\n")
        lines = [
            f"Filepath: {self.url}",
            f"Lines: {line_count}",
        ]
        length = max(map(len, lines))
        return "\n".join(
            [
                "",
                "/" + "*" * (length + 5),
                *(f"*  {line:<{length}}  *" for line in lines),
                "*" * (length + 5) + "/",
                content,
            ]
        )


class XMLAsset(WebAsset):
    """OWL template (.xml) asset, consumed as parsed elements by ``xml()``."""

    @functools.cached_property
    def _parsed_root(self) -> etree._Element:
        """Parse the asset's XML source exactly once; cache the root element.

        ``template_elements`` (the only production consumer of this asset
        type) derives from this single parse. Previously the source was
        parsed here and then re-parsed by ``AssetsBundle.xml()`` from a
        serialized string — a wasted parse/serialize/parse round-trip per
        template file.
        """
        try:
            # Mirror ``WebAsset.content``'s ``inline or fetch`` (inline is the
            # empty string for file-backed assets — see _get_asset_content).
            raw = self.inline or WebAsset._fetch_content(self)
        except AssetError as e:
            raise self._error(str(e)) from e
        parser = etree.XMLParser(
            ns_clean=True, remove_comments=True, resolve_entities=False
        )
        try:
            return etree.fromstring(raw.encode("utf-8"), parser=parser)
        except etree.XMLSyntaxError as e:
            raise self._error(f"Invalid XML template: {e.msg}") from e

    @functools.cached_property
    def template_elements(self) -> list[etree._Element]:
        """Return the individual template elements parsed from this asset.

        Consumed directly by ``AssetsBundle.xml()`` instead of re-parsing the
        serialized content. For a ``<templates>``/``<template>``/``<odoo>``
        wrapper the children are the templates; any other root tag is itself a
        single template element. This reproduces exactly what ``xml()`` used to
        obtain by wrapping the serialized content in ``<templates>`` and
        re-parsing it.
        """
        root = self._parsed_root
        if root.tag in ("templates", "template", "odoo"):
            # Keep elements only: the parser strips comments but not
            # processing instructions, and a PI reaching ``xml()`` aborts
            # the bundle with a misleading "Template name is missing."
            return [el for el in root if isinstance(el.tag, str)]
        return [root]

    def _error(self, msg: str) -> XMLAssetError:
        """Log and build the contextualized error; the caller raises it.

        Unlike ``JavascriptAsset.generate_error`` (which returns a JS stub
        embedded in the bundle), XML template problems abort the whole
        bundle — keeping the ``raise`` at the call site makes that control
        flow visible instead of hiding it behind a same-named method with
        a different contract.
        """
        return XMLAssetError(super().generate_error(msg))


class StylesheetAsset(WebAsset):
    """Plain CSS asset with relative-URL rewriting and regex minification."""

    rx_import = re.compile(r"""@import\s+('|")(?!'|"|/|https?://)""", re.UNICODE)
    # ``rx_url`` matches ``url(`` followed by the optional opening quote
    # and captures the relative body up to (but not including) the
    # closing quote or paren.  Capturing the body lets us prefix
    # ``web_dir/`` and then collapse any ``<dir>/../<seg>`` produced by
    # the concatenation.  Without the collapse, the emitted URL in the
    # bundle doesn't match ``<link rel="preload" href="…">`` byte-for-
    # byte, so the browser considers the preload unused even though the
    # normalised fetch target is identical — see
    # knowledge/.../2026-04-19-esm-import-map-conflict-investigation.md
    # §10.2 for the FA-solid preload example.
    rx_url = re.compile(
        r"""(?<!")url\s*\(\s*(?P<q>['"]|)(?!['"]|/|https?://|data:|\#\{str)(?P<body>[^'")\s]*)""",
        re.UNICODE,
    )
    rx_charset = re.compile(r'(@charset "[^"]+";)', re.UNICODE)
    # The two CSS spans minification must NOT reach into — comments and string
    # literals — tokenized by the shared module-level ``_CSS_STRING_OR_COMMENT``
    # (see its definition for the alternation-order rationale: whichever of a
    # comment/string opens first at a position wins, so the text between matches
    # is ordinary CSS, safe to whitespace-collapse). Reused here so the masking
    # minifier and ``_rewrite_css_outside_strings`` cannot drift — the same
    # tokenizer decides what both treat as opaque.
    _CSS_TOKEN_RE = _CSS_STRING_OR_COMMENT

    def __init__(
        self, *args: Any, rtl: bool = False, autoprefix: bool = False, **kw: Any
    ) -> None:
        self.rtl = rtl
        self.autoprefix = autoprefix
        # Per-asset fetch/rewrite errors, recorded by ``_fetch_content`` and
        # harvested into the bundle's ``css_errors`` by ``preprocess_css``. The
        # asset no longer reaches up to mutate the bundle's list (a leaf writing
        # its container's state), so its error path is exercisable without a
        # live bundle. This lives on StylesheetAsset rather than the WebAsset
        # base on purpose: "record the problem and degrade to empty output" is
        # the *stylesheet* recovery policy. JS assets degrade by emitting a
        # console.error stub into their content, and XML assets treat a content
        # error as fatal (raise XMLAssetError) — neither needs this list.
        self.errors: list[str] = []
        super().__init__(*args, **kw)

    @functools.cached_property
    def unique_descriptor(self) -> str:
        direction = (self.rtl and "rtl") or "ltr"
        autoprefixed = (self.autoprefix and "autoprefixed") or ""
        return (
            f"{self.url or self.inline},{self.last_modified},{direction},{autoprefixed}"
        )

    def _fetch_content(self) -> str:
        try:
            content = super()._fetch_content()
            # ``self.url`` is a forward-slash web path: resolve its directory
            # with posixpath, NOT pathlib.Path. ``Path`` is ``WindowsPath`` on
            # Windows, so its ``.parent`` would emit backslashes that then leak
            # into the rewritten web URLs (and break the ``url()`` normpath).
            web_dir = posixpath.dirname(self.url)

            def _rewrite_import(match: re.Match[str]) -> str:
                # Function replacement (mirrors ``_rewrite_url``): never splice
                # ``web_dir`` into a regex replacement TEMPLATE. A backslash in
                # the path (e.g. a stray ``\w``) would be reparsed as an invalid
                # replacement escape and raise ``re.PatternError`` — which, not
                # being an ``AssetError``, escapes the handler below.
                return f"@import {match.group(1)}{web_dir}/"

            if self.rx_import:
                content = _rewrite_css_outside_strings(
                    self.rx_import, _rewrite_import, content
                )

            def _rewrite_url(match: re.Match[str]) -> str:
                # Prefix the bundled URL with ``web_dir`` and then
                # collapse redundant ``<dir>/../`` segments so the
                # rewritten ``url(…)`` is byte-identical to the
                # URL a ``<link rel="preload">`` tag would use.
                # An empty body (``url()``) stays empty after the
                # normpath round-trip since ``posixpath.normpath("/a/b/")``
                # strips the trailing slash; the empty-body branch
                # preserves the old "no body" no-op behaviour.
                #
                # This rewrite is applied via ``_rewrite_css_outside_strings``,
                # so a ``url(...)`` that is literal text inside a
                # ``content: "…"`` value (or a comment) is skipped — the match
                # starts inside a protected span. A real ``url("x")`` is still
                # rewritten: its match starts at the ``url(`` token, in code,
                # and only the inner ``"x"`` is protected, which this rewrite
                # never enters.
                q = match.group("q")
                body = match.group("body")
                if not body:
                    return f"url({q}{web_dir}/"
                normalised = posixpath.normpath(f"{web_dir}/{body}")
                return f"url({q}{normalised}"

            content = _rewrite_css_outside_strings(self.rx_url, _rewrite_url, content)

            # remove charset declarations, we only support utf-8
            return self.rx_charset.sub("", content)
        except AssetError as e:
            self.errors.append(str(e))
            return ""

    def get_source(self) -> str:
        # ``odoo-split:`` namespaces the marker so it cannot collide with a
        # legitimate CSS loud comment Sass preserves — see ``CssPipeline.rx_css_split``.
        content = self.inline or self._fetch_content()
        return f"/*! odoo-split:{self.id} */\n{content}"

    @classmethod
    def _minify_css_body(cls, content: str) -> str:
        """Minify CSS text, leaving string literals and legal comments intact.

        Strategy: mask the two spans minification must not touch — string
        literals and ``/*! … */`` legal comments (license headers: FontAwesome,
        Bootstrap dist) — behind inert NUL-delimited placeholders, drop ordinary
        comments, then run the SAME whitespace-collapse + brace-tighten the
        legacy pipeline used, and restore the masked spans verbatim. Because the
        placeholders carry no whitespace or braces, that collapse reproduces the
        legacy structural output byte-for-byte — the only behavioural change is
        that string/legal-comment interiors are no longer corrupted. The old
        pipeline ran the regexes string-unaware, so ``content: "a  b"`` lost a
        space and ``content: "/* x */"`` lost its inner ``/* x */``.

        :attr:`_CSS_TOKEN_RE`'s alternation order is what makes the masking
        correct across interleaving: a ``"`` opened inside a comment is consumed
        by the comment arm, and a ``/*`` inside a string by the string arm.

        A pre-existing ``/*# sourceMappingURL=… */`` link (re-minifying makes the
        old mapping meaningless) needs no separate pass: it is an ordinary block
        comment, so the mask step below drops it like any other — and, because
        that step is string-aware, a ``sourceMappingURL`` written inside a
        ``content: "…"`` value survives. The old leading whole-text
        ``rx_sourceMap.sub`` was the one pass that reached into strings.

        Both JS minifiers preserve legal comments the same way (rjsmin
        ``keep_bang_comments``, esbuild ``--legal-comments=inline``).

        Header-less so it is unit-testable and comparable to the legacy pipeline
        without the per-file ``with_header`` prefix; :meth:`minify` adds the header.
        """
        # NUL is invalid in CSS (the spec replaces U+0000 with U+FFFD). Strip it
        # so source text can never collide with the NUL-delimited mask
        # placeholders below: an un-masked ``\x00<digits>\x00`` in the input would
        # otherwise be caught by the restore regex and index into ``protected``
        # — an IndexError that takes down the whole bundle's CSS compile.
        content = content.replace("\x00", "")

        protected: list[str] = []

        def _mask(match: re.Match[str]) -> str:
            token = match.group()
            if token[0] in "\"'" or token.startswith("/*!"):
                protected.append(token)
                return f"\x00{len(protected) - 1}\x00"
            return ""  # ordinary comment — dropped

        masked = cls._CSS_TOKEN_RE.sub(_mask, content)
        masked = re.sub(r"\s+", " ", masked)
        masked = re.sub(r" *([{}]) *", r"\1", masked)
        # Restore via a function replacement so backslashes inside a string
        # literal are not reinterpreted as regex escapes.
        return re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], masked)

    def minify(self) -> str:
        # In debug, ``css_with_sourcemap`` rebuilds the bundle from each asset's
        # ``content`` and the minified join ``preprocess`` produces is consumed
        # only for @import extraction (which unminified content serves equally
        # well, @imports surviving the whitespace collapse either way), so the
        # regex passes here are pure wasted work per render — skip them,
        # mirroring ``ScssStylesheetAsset.minify``. The served debug CSS is
        # unminified regardless, so output is byte-identical. Production
        # (non-debug) still minifies: there the join IS the ``.min.css`` body.
        # ``getattr`` default False = "minify": a real bundle always carries
        # ``is_debug_assets``, so the default only applies to minimal bundle
        # stubs (some preprocess unit tests), which expect the prior
        # always-minify behaviour.
        if getattr(self.bundle, "is_debug_assets", False):
            return self.with_header(self.content)
        return self.with_header(self._minify_css_body(self.content))


class PreprocessedCSS(StylesheetAsset):
    """Base for stylesheet dialects compiled through an external CLI."""

    rx_import = None

    # Whole-bundle SCSS of the largest bundles takes tens of seconds on the
    # CLI fallback path; generous, but a hung compiler must not pin a worker.
    _COMPILE_TIMEOUT_S: int = 180

    def get_command(self) -> list[str]:
        """Return the compiler argv reading source on stdin."""
        raise NotImplementedError

    def compile(self, source: str) -> str:
        """Compile ``source`` through :meth:`get_command`; raise ``CompileError``."""
        return _run_cli_pipe(self.get_command(), source, self._COMPILE_TIMEOUT_S)


class ScssStylesheetAsset(PreprocessedCSS):
    """Compile SCSS (.scss) using Dart Sass (embedded protocol or CLI)."""

    # Process-wide one-shot guard for the embedded-Sass → CLI fallback warning
    # (see :meth:`_warn_embedded_fallback`). A class attribute, not a module
    # global, so flipping it needs no ``global`` statement.
    _embedded_fallback_warned = False

    @classmethod
    def _warn_embedded_fallback(cls, exc: Exception) -> None:
        """Surface the embedded-Sass → CLI degrade: WARNING once, then DEBUG.

        A broken sass-embedded install otherwise logs the (much slower)
        per-compile CLI fallback only at DEBUG, so the regression is invisible
        at the default log level. Warn once per process; later fallbacks stay
        at DEBUG so a persistent failure does not flood the log.
        """
        if cls._embedded_fallback_warned:
            _logger.debug("Dart Sass embedded unavailable, using CLI", exc_info=exc)
            return
        ScssStylesheetAsset._embedded_fallback_warned = True
        _logger.warning(
            "Embedded Dart Sass unavailable (%s); falling back to the Dart Sass "
            "CLI for every SCSS compile. The CLI path is markedly slower (a "
            "per-bundle subprocess, up to %ss) — install/repair sass-embedded to "
            "restore the fast path. This warning fires once per process.",
            exc,
            cls._COMPILE_TIMEOUT_S,
        )

    @property
    def bootstrap_path(self) -> str:
        return file_path("web/static/lib/bootstrap/scss")

    @property
    def output_style(self) -> str:
        """Use compressed output in production for AST-aware minification."""
        return (
            "expanded" if self.bundle and self.bundle.is_debug_assets else "compressed"
        )

    @property
    def _sass_syntax(self) -> str:
        """Sass syntax identifier for this asset type."""
        return "scss"

    def minify(self) -> str:
        """Dart Sass output needs no regex pass.

        Production output is already ``compressed``; in debug mode the
        ``preprocess_css`` join this feeds is consumed only for
        ``@import`` extraction (``css_with_sourcemap`` rebuilds the
        bundle from ``asset.content``), so regex-minifying the expanded
        output there was pure wasted work per debug render.
        """
        return self.with_header()

    def compile(self, source: str) -> str:
        """Compile SCSS: embedded Dart Sass -> Dart Sass CLI."""
        import odoo.addons

        # Try 1: Embedded Sass Protocol (fast, custom importers)
        try:
            # ``SassCompileError`` is the module-level import (top of file); only
            # the embedded-protocol-specific symbols are imported lazily here.
            from odoo.tools.sass_embedded import (
                OdooSassImporter,
                get_sass_compiler,
            )

            compiler = get_sass_compiler()
            profiler.force_hook()
            return compiler.compile_string(
                source,
                syntax=self._sass_syntax,
                importers=[OdooSassImporter(self.bootstrap_path)],
                load_paths=[self.bootstrap_path, *odoo.addons.__path__],
                style=self.output_style,
                quiet_deps=True,
            )
        except SassCompileError:
            raise
        except Exception as exc:
            # A broken/unavailable embedded compiler (SassProtocolError, a dead
            # subprocess, …) — NOT a real SCSS error, which is SassCompileError
            # and re-raised above — degrades to the CLI. Surface it ONCE at
            # WARNING so the much slower fallback is not invisible at the default
            # log level (see :meth:`_warn_embedded_fallback`).
            self._warn_embedded_fallback(exc)
            # Close the singleton to reap any zombie process.
            from odoo.tools.sass_embedded import close_sass_compiler

            close_sass_compiler()

        # Try 2: Dart Sass CLI (no custom importers, uses --load-path)
        return super().compile(source)

    def get_command(self) -> list[str]:
        """Build the Dart Sass CLI command."""
        import odoo.addons

        sass = find_sass() or "sass"
        load_paths = [self.bootstrap_path, *odoo.addons.__path__]
        cmd = [
            sass,
            "--stdin",
            "--no-source-map",
            "--style",
            self.output_style,
            "--quiet-deps",
            "--silence-deprecation=import",
            "--silence-deprecation=global-builtin",
            "--silence-deprecation=if-function",
            "--silence-deprecation=duplicate-var-flags",
            "--silence-deprecation=color-functions",
        ]
        for path in load_paths:
            cmd.extend(["--load-path", path])
        return cmd


# ESM bundle classification is validated when ``esm_registry()`` first
# builds (lazily — the manifest walk needs the configured addons paths).

# Cross-check the import-map external-libs registry against esbuild's
# alias list.  Both declaration sites now live outside ir_qweb
# (``odoo.libs.constants`` / ``odoo.tools.assets.esbuild``), so the check runs
# here instead of at the bottom of ir_qweb.
AssetsBundle._validate_external_libs(set(ODOO_EXTERNAL_LIBS))
