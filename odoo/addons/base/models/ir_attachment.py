import base64
import contextlib
import functools
import io
import logging
import mimetypes
import os
import re
import time
import uuid
from collections import defaultdict
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from odoo import _, api, fields, models, modules
from odoo.api import ValuesType
from odoo.exceptions import (
    AccessError,
    MissingError,
    UserError,
    ValidationError,
)
from odoo.fields import COLLECTION_TYPES, Domain
from odoo.http import Stream, request, root
from odoo.libs.constants import PREFETCH_MAX
from odoo.libs.filesystem.mimetypes import (
    MIMETYPE_HEAD_SIZE,
    _olecf_mimetypes,
    fix_filename_extension,
    guess_mimetype,
)
from odoo.tools import (
    OrderedSet,
    config,
    consteq,
    file_open,
    human_size,
    image,
    str2bool,
)
from odoo.tools.hashing import (
    ALGO_TAG,
    CONTENT_DIGEST_MAX_LEN,
    content_hash,
    content_hasher,
)
from odoo.tools.misc import limited_field_access_token

from odoo.addons.base.models.ir_attachment_storage import (
    STORAGE_BACKENDS,
    AttachmentStorage,
    FileStorage,
    backend_for_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Generator

    from odoo.tools.query import Query

_logger = logging.getLogger(__name__)
SECURITY_FIELDS = ("res_model", "res_id", "create_uid", "public", "res_field")


@functools.cache
def _resolve_filestore_root(filestore: str) -> Path:
    """Resolve the filestore root once per path string (cached).

    ``_full_path`` runs on every filestore access and ``Path.resolve()`` costs
    a per-component syscall walk. Re-pointing the root symlink mid-run requires
    a restart.
    """
    return Path(filestore).resolve()


def condition_values(
    model: Any, field_name: str, domain: Domain
) -> Collection[Any] | None:
    """Extract the restricted values for *field_name* from *domain*.

    :return: the values of an ``=`` or ``in`` condition on *field_name*, or
        ``None`` when the domain does not restrict the field with those
        operators. Also ``None`` for a lazy value (``Query``/``SQL``/
        ``Domain``): probing it with ``in``/``len()`` would execute the
        subquery, so treat it as unrestricted (the safe over-approximation).
    """
    domain = domain.optimize(model)
    # Keep only '='/'in' conditions on *field_name* (else TRUE), re-optimize.
    # optimize() merges same-field conditions, so at most one remains; a field
    # OR'd with another collapses to None (treated as unrestricted).
    field_only = domain.map_conditions(
        lambda cond: (
            cond
            if cond.field_expr == field_name and cond.operator in ("in", "=")
            else Domain.TRUE
        )
    ).optimize(model)
    condition = next(iter(field_only.iter_conditions()), None)
    if condition is None:
        return None
    # Normalize '=' to a list for uniform handling by callers
    if condition.operator == "=":
        return [condition.value]
    if isinstance(condition.value, COLLECTION_TYPES):
        return condition.value
    return None


class IrAttachment(models.Model):
    """Attachments link binary files or URLs to any Odoo document.

    Content storage is pluggable: subclass
    :class:`~odoo.addons.base.models.ir_attachment_storage.AttachmentStorage`
    and register it with ``@register_storage``. The write side
    (:meth:`_storage_backend`, driven by the ``ir_attachment.location``
    parameter) decides where NEW content goes; the read side follows the
    record's store key by URI scheme (:meth:`_backend_for_key`), so rows
    written before a location switch keep working. Plain sharded keys
    (``ab/<digest>``, optionally algorithm-tagged as ``b3/ab/<digest>``) belong
    to the local filestore, which names and dedups files by the digest of their
    content (:meth:`_file_store_path`).

    ``migration_domain`` (used by :meth:`force_storage`) is backend-defined: a
    backend must match every row it does not own to claim it. The ``_file_*``
    methods are the local-filestore primitives.

    Comments carry ``IRA-*`` tags cross-referencing an invariant to the test
    pinning it (grep the tag across this module and ``base/tests``).
    """

    _name = "ir.attachment"
    _description = "Attachment"
    _order = "id desc"

    name = fields.Char("Name", required=True)
    description = fields.Text("Description")
    res_name = fields.Char(
        "Resource Name",
        compute="_compute_res_name",
    )
    res_model = fields.Char("Resource Model")
    res_field = fields.Char("Resource Field")
    res_id = fields.Many2oneReference(
        "Resource ID",
        model_field="res_model",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        change_default=True,
        default=lambda self: self.env.company,
    )
    type = fields.Selection(
        [("url", "URL"), ("binary", "File")],
        string="Type",
        required=True,
        default="binary",
        change_default=True,
        help="You can either upload a file from your computer or copy/paste an internet link to your file.",
    )
    url = fields.Char("Url", index="btree_not_null", size=1024)
    public = fields.Boolean("Is public document")
    access_token = fields.Char("Access Token", groups="base.group_user")

    # Direct db_datas create/write bypasses the content pipeline (no checksum/
    # file_size/index, no storage dispatch); use 'raw'/'datas' for normal
    # content. test_http static-serve relies on this raw-column escape hatch.
    db_datas = fields.Binary("Database Data", attachment=False)
    store_fname = fields.Char("Stored Filename", index=True)
    file_size = fields.Integer("File Size", readonly=True)
    # Sized from the schema-wide invariant, not from today's algorithm: digests
    # of different vintages coexist by design (BLAKE3 at 64, legacy sha1 at 40,
    # which existing rows keep until they are rewritten). `hashing` raises at
    # import if the two ever stop agreeing.
    checksum = fields.Char("Checksum", size=CONTENT_DIGEST_MAX_LEN, readonly=True)
    mimetype = fields.Char("Mime Type", readonly=True)
    index_content = fields.Text("Indexed Content", readonly=True, prefetch=False)

    # the field 'datas' is computed and may use the other fields below
    raw = fields.Binary(
        string="File Content (raw)",
        compute="_compute_raw",
        inverse="_inverse_raw",
    )
    datas = fields.Binary(
        string="File Content (base64)",
        compute="_compute_datas",
        inverse="_inverse_datas",
    )

    _res_field_idx = models.Index("(res_model, res_field, res_id)")
    _checksum_idx = models.Index("(checksum) WHERE checksum IS NOT NULL")

    # Max res_model values for which _search builds a per-model security domain
    # (one comodel subquery each); above this, the fetch-and-filter fallback.
    _SEARCH_MODEL_DOMAIN_LIMIT = 5

    # Lowest-id window _audit_url_attachments materializes/tracks per run; the
    # logged total is unaffected. Bounds memory and the persisted url_audit_seen.
    _URL_AUDIT_WINDOW = 20

    # Cap bytes scanned/stored by _index: a large text upload would otherwise
    # spill unbounded index_content into the DB; full-text search needs a prefix.
    _INDEX_MAX_BYTES = 4 * 1024 * 1024

    # Chunk size for streaming uploads: peak memory per upload is O(this),
    # not O(file size).
    _STREAM_CHUNK_SIZE = 128 * 1024

    # Chunk size for the dedup collision comparison (see _streams_equal).
    _COMPARE_BLOCK_SIZE = 65536

    # Age (seconds) after which a leftover file in the filestore tmp/ dir is
    # swept as orphaned. Uploads stage there before the atomic move; a worker
    # killed mid-upload leaks a temp the content GC never sees. Must exceed the
    # longest legitimate upload so an in-flight temp is never collected.
    _FILESTORE_TMP_MAX_AGE = 24 * 3600

    # Cap checklist entries per filestore-GC run: the sweep holds a SHARE MODE
    # lock on ir_attachment throughout (blocking every attachment write), and a
    # bulk delete can leave hundreds of thousands of entries. The rest wait for
    # the next nightly run. See FileStorage.autovacuum.
    _GC_MAX_ENTRIES = 100_000

    # Min age (seconds) of a checklist marker before the filestore GC may sweep
    # it (IRA-G1). Content is written and GC-marked BEFORE the row's INSERT is
    # flushed, so until then the creating transaction holds no lock: a
    # concurrent GC's SHARE lock is granted, its whitelist query can't see the
    # uncommitted row, and it would delete content a committing store_fname will
    # point at. The marker mtime is the grace clock (refreshed on every re-mark,
    # dedup hits included); must exceed the longest content-writing transaction.
    _GC_CHECKLIST_GRACE = 24 * 3600

    def _check_res_field_access(self, res_model: str, res_field: str) -> None:
        """Validate write access to a field-backing attachment's target field.

        ``res_field`` is a plain Char with no ``groups``, so mutating it would
        bypass the field-group ACL that ``_check_access`` enforces on read;
        mirror that check at create/write time (IRA-L2).

        :raise AccessError: if the user cannot access the comodel field
        """
        if self.env.su or self.env.is_system() or not res_field:
            return
        comodel = self.env.get(res_model)
        field = comodel._fields.get(res_field) if comodel is not None else None
        if field is None or not comodel._has_field_access(field, "write"):
            raise AccessError(_("Sorry, you are not allowed to access this document."))

    @api.model
    def _decode_datas(self, datas: Any) -> bytes:
        """Decode a base64 ``datas`` payload as bytes; falsy decodes to ``b""``.

        The single decode wrapper for every ``datas`` entry point. ``b64decode``
        raises ``ValueError`` (bad padding/length or non-ASCII); surface it as a
        :class:`UserError` instead of a 500.

        :raise UserError: if *datas* is not valid base64
        """
        try:
            return base64.b64decode(datas or b"")
        except ValueError as exc:
            raise UserError(_("Attachment is not encoded in base64.")) from exc

    def _normalize_content_vals(self, vals: dict[str, Any]) -> bool:
        """Collapse the content keys of create/write *vals* into a single ``raw``.

        Single source of truth shared by :meth:`create` and :meth:`write`.
        Mutates *vals* in place:

        * ``raw`` wins over ``datas`` by KEY PRESENCE, not truthiness (IRA-A3);
        * ``str`` content is encoded to ``bytes``, empty/absent normalizes to ``b""``;
        * the derived metadata columns (``file_size``/``checksum``/
          ``store_fname``/``index_content``) are stripped — settable only
          internally, never through the public API. ``index_content`` had been
          left out, letting a writer inject full-text index text (IRA-C3).

        Vals carrying neither ``raw`` nor ``datas`` are left untouched (url
        rows, ``db_datas`` passthrough): not treated as empty content (IRA-R1).

        :return: whether *vals* carried a content key (``raw`` or ``datas``)
        """
        has_content = "raw" in vals or "datas" in vals
        # 'datas' is always popped to bypass `_inverse_datas`; 'raw' is the
        # single channel from here on.
        datas = vals.pop("datas", None)
        if "raw" in vals:
            raw = vals["raw"] or b""
            vals["raw"] = raw.encode() if isinstance(raw, str) else raw
        elif has_content:  # only 'datas' was provided
            vals["raw"] = self._decode_datas(datas)
        for field in ("file_size", "checksum", "store_fname", "index_content"):
            vals.pop(field, None)
        return has_content

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    # Content-metadata derivation runs in TWO places BY DESIGN — do not unify:
    # create() derives inline and pops 'raw' (write-as-we-go keeps a batch flat
    # in memory); write() leaves 'raw' and lets _inverse_raw derive it. Both
    # share _normalize_content_vals + _get_datas_related_values. Unifying them
    # reintroduces the O(total bytes) buffering this split avoids.
    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        # Copy first: _normalize_content_vals mutates in place and the caller's
        # dicts must not be touched (model_create_multi contract).
        vals_list = [dict(vals) for vals in vals_list]

        # Fail-fast on the create ACL before the content pipeline: super().create()
        # re-checks, but only after content hashing, _index and the filestore write
        # have run for a user who cannot create. No-op under su. Check on an EMPTY
        # recordset — create() may run on a populated one (copy()), where a
        # non-empty check would evaluate record-level 'create' rules on existing
        # rows (the pattern _check_access documents for create()).
        self.browse().check_access("create")

        # Run the comodel/field access checks on cheap metadata BEFORE content
        # post-processing, else an unauthorized create still pays for content
        # hashing, _index and autoresize it will reject (as write() does).
        model_and_ids = defaultdict(OrderedSet)  # {res_model: {res_id}}
        for values in vals_list:
            # a new res_field must pass the comodel field's ACL (IRA-L2)
            if res_field := values.get("res_field"):
                self._check_res_field_access(values.get("res_model"), res_field)
            # Group by model so the comodel access check issues one query per
            # model, not per attachment.
            model_and_ids[values.get("res_model")].add(values.get("res_id"))
        if any(self._inaccessible_comodel_records(model_and_ids, "write")):
            raise AccessError(_("Sorry, you are not allowed to access this document."))

        # Access granted: run the content pipeline. Resolve the write-side
        # backend once for the whole batch.
        backend = self._storage_backend()
        # {(checksum, mimetype): datas-related values}: a batch repeating a
        # payload (mail templates, imports) otherwise re-runs _index, the hash
        # pass and the filestore write per row. The memo dedups derivation and,
        # since _get_datas_related_values persists content, writes each distinct
        # payload once. Keyed on checksum, NOT id(raw): the 'datas' path decodes
        # a distinct object per row, and pinning payloads to make id() sound
        # would retain O(total bytes). Writing before super().create() is safe:
        # content-addressed, so a rollback just leaves a GC-marked orphan.
        derived_values: dict[tuple[str, str], dict[str, Any]] = {}
        for values in vals_list:
            # Shared raw/datas precedence + metadata stripping (IRA-A3).
            has_content = self._normalize_content_vals(values)

            # _check_contents mutates and returns `values`; if an override forks
            # a new dict, create() stays correct because _inverse_raw re-derives
            # metadata post-create.
            values = self._check_contents(values)
            if has_content:
                # pop() so _inverse_raw does not re-process content after create.
                raw = values.pop("raw")
                # Derive metadata even for explicitly empty content, so an
                # emptied attachment is identical created or written (IRA-P0-7).
                # Content-less vals were left untouched above (IRA-R1): defaulting
                # raw to b"" would stamp the digest of b"" over a caller's db_datas.
                memo_key = (self._content_checksum(raw), values["mimetype"])
                if memo_key not in derived_values:
                    # Persists the payload (once per memo_key) and returns the
                    # store fragment; `raw` is rebound each iteration so the
                    # payload is released instead of accumulating O(total bytes).
                    derived_values[memo_key] = self._get_datas_related_values(
                        raw, values["mimetype"], backend, checksum=memo_key[0]
                    )
                values.update(derived_values[memo_key])

        records = super().create(vals_list)
        records._check_serving_attachments()
        return records

    def write(self, vals: dict[str, Any]) -> bool:
        # Fail-fast: super().write() re-checks, but checking here avoids content
        # post-processing for a user who cannot write. Skipped under sudo.
        self.check_access("write")
        if "res_model" in vals or "res_id" in vals:
            model_and_ids = defaultdict(OrderedSet)
            if "res_model" in vals and "res_id" in vals:
                model_and_ids[vals["res_model"]].add(vals["res_id"])
            else:
                for record in self:
                    model_and_ids[vals.get("res_model", record.res_model)].add(
                        vals.get("res_id", record.res_id)
                    )
            if any(self._inaccessible_comodel_records(model_and_ids, "write")):
                raise AccessError(
                    _("Sorry, you are not allowed to access this document.")
                )
        # a changed res_field must pass the comodel field's ACL (IRA-L2)
        if res_field := vals.get("res_field"):
            if "res_model" in vals:
                self._check_res_field_access(vals["res_model"], res_field)
            else:
                # One check per distinct comodel: the field ACL is deterministic
                # per (res_model, res_field, operation, user).
                for res_model in OrderedSet(record.res_model for record in self):
                    self._check_res_field_access(res_model, res_field)
        # Normalize content keys like create() (shared helper): without it the
        # two inverses run in vals key order and the last key silently wins —
        # the opposite of create() — decoding the payload several times.
        has_content = self._normalize_content_vals(vals)
        if has_content or "mimetype" in vals:
            vals = self._check_contents(vals)
        res = super().write(vals)
        if "url" in vals or "type" in vals:
            self._check_serving_attachments()
        return res

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        if not default.keys() & {"datas", "db_datas", "raw"}:
            # No content override: preserve the original. db-stored content is
            # carried via `raw` (checksum recomputed); filestore-backed rows are
            # relinked to their existing file in copy() without reading bytes
            # (IRA-B4: reading them re-deduped to the same file, and a transient
            # read failure silently produced an empty copy).
            for attachment, vals in zip(self, vals_list, strict=True):
                # Carry content only when the original HAS content: checksum for
                # pipeline content, db_datas for the escape hatch. A content-less
                # row has neither — carrying raw=b"" would stamp the digest of
                # b""/file_size=0 the original never had (IRA-C4).
                if not attachment.store_fname and (
                    attachment.checksum or attachment.db_datas
                ):
                    vals["raw"] = attachment.raw
        return vals_list

    def copy(self, default: ValuesType | None = None) -> Self:
        new_attachments = super().copy(default)
        if not (default or {}).keys() & {"datas", "db_datas", "raw"}:
            # Relink filestore-backed copies to the original file (same checksum
            # and store path, zero bytes read; see copy_data). create() stripped
            # the metadata, so restore it via a direct super().write, bypassing
            # subclass overrides like _set_attachment_data does. strict zip:
            # copy_data may drop duplicate-id entries, where positional relinking
            # is impossible — fail loudly rather than leave empty copies.
            for origin, copied in zip(self, new_attachments, strict=True):
                if origin.store_fname:
                    super(IrAttachment, copied.sudo()).write(
                        {
                            "store_fname": origin.store_fname,
                            "checksum": origin.checksum,
                            "file_size": origin.file_size,
                            "index_content": origin.index_content,
                            "db_datas": False,
                        }
                    )
        return new_attachments

    def unlink(self) -> bool:
        # Delete in the database first, then the filesystem: avoids errors when
        # concurrent transactions delete the same file and some get rolled back.
        # (Asset-bundle ormcache invalidation lives in ir_attachment_assets.py.)
        to_delete = OrderedSet(
            attach.store_fname for attach in self if attach.store_fname
        )
        res = super().unlink()
        # key-axis dispatch: content follows its store key, not the configured
        # location. Batched: plain keys are GC-marked in one grouped pass.
        self._storage_delete_multi(to_delete)
        return res

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_res_name(self) -> None:
        to_compute = self.filtered(lambda a: a.res_model and a.res_id)
        (self - to_compute).res_name = False
        for res_model, attachments in to_compute.grouped("res_model").items():
            if res_model not in self.env:
                # Model no longer exists (module uninstalled) — degrade gracefully
                for attachment in attachments:
                    attachment.res_name = False
                continue
            res_ids = attachments.mapped("res_id")
            # Drop ids that no longer exist (dangling res_id → MissingError) or
            # the user cannot read (restricted record → AccessError) reading
            # display_name; both degrade to res_name = False.
            records = self.env[res_model].browse(res_ids).exists()
            records = records._filtered_access("read")
            name_map = {record.id: record.display_name for record in records}
            for attachment in attachments:
                attachment.res_name = name_map.get(attachment.res_id, False)

    @api.depends("store_fname", "db_datas", "file_size")
    @api.depends_context("bin_size")
    def _compute_datas(self) -> None:
        if self.env.context.get("bin_size"):
            for attach in self:
                attach.datas = human_size(attach.file_size)
            return

        for attach in self:
            attach.datas = base64.b64encode(attach.raw or b"")

    @api.depends("store_fname", "db_datas")
    def _compute_raw(self) -> None:
        for attach in self:
            # `_stored_content` is the shared keyed-backend / inline-db_datas
            # triage (see _read_prefix, which adds the addon-static url leg on
            # top). None means "this row stores nothing", which for `raw` is the
            # empty value the field already had.
            attach.raw = attach._stored_content()

    # ------------------------------------------------------------
    # INVERSE METHODS
    # ------------------------------------------------------------

    def _inverse_raw(self) -> None:
        self._set_attachment_data(lambda a: a.raw or b"")

    def _inverse_datas(self) -> None:
        # Unreachable in practice: create()/write() both route `datas` through
        # `_normalize_content_vals`, which pops it in favour of `raw`, so every
        # public write lands on `_inverse_raw` instead. It stays because the
        # `inverse=` wiring is what makes `datas` writable at all — dropping it
        # makes the field readonly and silently DISCARDS `write({'datas': ...})`.
        # It decodes through `_decode_datas` like every other entry point, so a
        # direct caller gets the same UserError rather than a bare ValueError.
        self._set_attachment_data(lambda attach: self._decode_datas(attach.datas))

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    @api.model
    def _search(
        self,
        domain: Any,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        *,
        active_test: bool = True,
        bypass_access: bool = False,
    ) -> Query:
        assert not self._active_name, "active name not supported on ir.attachment"
        disable_binary_fields_attachments = False
        domain = Domain(domain)
        if (
            not self.env.context.get("skip_res_field_check")
            and not any(
                d.field_expr in ("id", "res_field") for d in domain.iter_conditions()
            )
            and not bypass_access
        ):
            disable_binary_fields_attachments = True
            domain &= Domain("res_field", "=", False)

        domain = domain.optimize(self)
        if self.env.su or bypass_access or domain.is_false():
            return super()._search(
                domain,
                offset,
                limit,
                order,
                active_test=active_test,
                bypass_access=bypass_access,
            )

        # General access rules
        # - public == True are always accessible
        sec_domain = Domain("public", "=", True)
        # - res_id == False needs to be system user or creator
        res_ids = condition_values(self, "res_id", domain)
        if not res_ids or False in res_ids:
            if self.env.is_system():
                sec_domain |= Domain("res_id", "=", False)
            else:
                sec_domain |= Domain("res_id", "=", False) & Domain(
                    "create_uid", "=", self.env.uid
                )

        # Search by res_model and res_id, filter using permissions from res_model
        # - res_id != False needs then check access on the linked res_model record
        # - res_field != False needs to check field access on the res_model
        res_model_names = condition_values(self, "res_model", domain)
        if 0 < len(res_model_names or ()) <= self._SEARCH_MODEL_DOMAIN_LIMIT:
            sec_domain |= self._search_models_security_domain(
                domain, res_model_names, disable_binary_fields_attachments
            )
            return super()._search(
                domain & sec_domain,
                offset,
                limit,
                order,
                active_test=active_test,
            )

        # No small res_model restriction (e.g. `('id', 'in', ...)`): restrict
        # with the domain and add all model-linked attachments. Batch the fetch
        # instead of materializing every matching row's security fields at once,
        # which was O(table) in memory for a non-system search (IRA-P1-3).
        domain &= sec_domain | Domain("res_model", "!=", False)
        domain = domain.optimize_full(self)
        ordered = bool(order)
        if limit is None:
            # the unbounded fallback still filters inaccessible rows via
            # _fetch_accessible_ids' per-batch _filtered_access (IRA-T1)
            result = self._fetch_accessible_ids(domain, order, None)
            return self.browse(result[offset:])._as_query(ordered)
        result = self._fetch_accessible_ids(domain, order, offset + limit)
        return self.browse(result[offset : offset + limit])._as_query(ordered)

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    @api.model
    def _backend_for_key(self, fname: str) -> AttachmentStorage:
        """Return the read-side backend owning the store key *fname*.

        Dispatch is by URI scheme (``s3://...``); plain sharded fnames
        belong to the local filestore.
        """
        return backend_for_key(self.env, fname)

    def _content_checksum(self, bin_data: bytes) -> str:
        """Return the content digest of *bin_data* (for content-addressed storage).

        The algorithm is :mod:`odoo.tools.hashing`'s content family (BLAKE3,
        sha1 without the extension); :meth:`_file_store_path` tags the store key
        with it, so digests of different vintages coexist in one filestore.
        """
        # an empty file has a checksum too (for caching)
        return content_hash(bin_data or b"")

    @api.model
    def _filestore(self) -> str:
        return config.filestore(self.env.cr.dbname)

    @api.model
    def _file_delete(self, fname: str) -> None:
        # add fname to the checklist; garbage-collected later
        self._file_delete_multi((fname,))

    @api.model
    def _file_delete_multi(self, fnames: Collection[str]) -> None:
        """Schedule local-filestore keys for collection (the GC checklist).

        THE override point for local-filestore deletion: the per-key path
        (:meth:`FileStorage.delete` via :meth:`_file_delete`) and the batched
        unlink path (:meth:`_storage_delete_multi`) both funnel through here.
        They used to diverge -- ``unlink()`` went straight to
        :meth:`_mark_for_gc_multi` -- so a deployment overriding
        :meth:`_file_delete` was invoked when content was *replaced* and
        silently skipped when a row was *deleted*.
        """
        self._mark_for_gc_multi(fnames)

    @api.model
    def _file_store_path(self, checksum: str) -> str:
        """Return the content-addressed relative store path (kept in ``store_fname``).

        Files are sharded across 256 directories by the first two hex chars of
        the digest; the filesystem work lives in
        :meth:`_get_path`/:meth:`_file_write`.

        Keys written by a non-sha1 digest carry its algorithm tag
        (``b3/<shard>/<digest>``).  That prefix is what makes an algorithm
        change *additive*: legacy untagged ``<shard>/<sha1>`` keys keep
        resolving forever (reads go through the stored ``store_fname``, never
        through this method), so switching costs no filestore rewrite and no
        downtime — only new writes land under the new prefix.  Nothing else in
        the filestore machinery cares: ``_full_path``, the GC checklist walk and
        ``_mark_for_gc`` are all depth-agnostic.

        Consequence to know: the two layouts dedup independently.  Content
        already stored under a sha1 key is written a second time under its b3
        key the first time it is re-uploaded, until the old row is rewritten or
        collected.  Convergence is deliberately left to normal row churn rather
        than a filestore-wide rehash.
        """
        # we use '/' in the db (even on windows)
        if ALGO_TAG == "s1":
            # historical untagged layout: the sha1 fallback must keep writing
            # (and finding) exactly the paths it always did
            return checksum[:2] + "/" + checksum
        return f"{ALGO_TAG}/{checksum[:2]}/{checksum}"

    @api.model
    def _file_read(self, fname: str, size: int | None = None) -> bytes:
        full_path = self._full_path(fname)
        try:
            with Path(full_path).open("rb") as f:
                return f.read(size)
        except OSError:
            _logger.info("_file_read reading %s", full_path, exc_info=True)
        return b""

    @contextlib.contextmanager
    def _staged_filestore_temp(self, prefix: str) -> Generator[Path]:
        """Yield a staging path under the filestore ``tmp/`` dir, cleaned up on failure.

        Content is written here first and only then atomically moved into its
        content-addressed path, so a crash never leaves a truncated file there
        (which would fail every future dedup comparison with a spurious
        collision and block re-uploads of that content forever). Staging in
        ``tmp/`` rather than the shard dir leaves any crash orphan where
        :meth:`_gc_stale_filestore_temps` can sweep it; ``tmp/`` shares the
        filestore root, so ``replace()`` into the shard stays atomic.

        Both writers open-coded this, and they disagreed about the cleanup
        scope: the buffered one unstaged only on ``OSError``, the streaming one
        on any exception. The streaming one has to, because it resolves its
        target (:meth:`_get_path`, which raises ``UserError`` on a digest
        collision) *inside* the staged region, having no key until the whole
        stream is hashed. The buffered one resolves its target first, so today
        nothing but an ``OSError`` can reach its staged region — the narrower
        cleanup was correct rather than buggy. Unifying on the broader form
        keeps it correct if that body ever grows, and leaves one protocol
        instead of two subtly different ones.
        """
        tmp_dir = Path(self._full_path("tmp"))
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"{prefix}-{uuid.uuid4().hex}"
        try:
            yield tmp_path
        except Exception as exc:
            if isinstance(exc, OSError):
                _logger.info("filestore staging failed for %s", tmp_path, exc_info=True)
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise

    @api.model
    def _file_write(self, bin_value: bytes, checksum: str) -> str:
        fname, full_path = self._get_path(bin_value, checksum)
        if Path(full_path).exists():
            # Dedup hit: (re-)mark to refresh the marker mtime (the GC grace
            # clock) for THIS transaction. The existing file may be an orphan
            # whose marker predates the grace window; without the refresh the GC
            # could sweep it before this transaction's INSERT flushes (IRA-G1).
            # Returning here keeps the dedup hit free of any file I/O, which is
            # why this writer checks the target itself instead of staging first
            # and letting the commit find out (as the streaming one must).
            self._mark_for_gc(fname)
            return fname
        with self._staged_filestore_temp("write") as tmp_path:
            with tmp_path.open("wb") as fp:
                fp.write(bin_value)
            tmp_path.replace(full_path)
        # add fname to checklist, in case the transaction aborts
        self._mark_for_gc(fname)
        return fname

    @api.model
    def _file_write_stream(
        self, fileobj: Any, *, chunk_size: int | None = None
    ) -> tuple[str, int, str]:
        """Stream *fileobj* into the filestore, hashing as it goes.

        Chunks *fileobj* to a temp file while updating a running digest, then
        atomically moves it into its content-addressed path (or drops it on a
        dedup hit). Peak memory is one chunk — the streaming counterpart of
        :meth:`_file_write`, which needs the full ``bytes`` up front.

        :param fileobj: a binary file-like supporting ``read(size)``
        :return: ``(store_fname, file_size, checksum)``; ``store_fname`` is
            ``""`` for empty content (kept inline as db_datas)
        """
        chunk_size = chunk_size or self._STREAM_CHUNK_SIZE
        digest = content_hasher()
        size = 0
        # Shared staging protocol (tmp/ + unique name + unconditional cleanup on
        # any failure, which this path needs because _get_path below can raise a
        # UserError on a digest collision).
        with self._staged_filestore_temp("stream") as tmp_path:
            with tmp_path.open("wb") as out:
                while chunk := fileobj.read(chunk_size):
                    if isinstance(chunk, str):
                        chunk = chunk.encode()
                    digest.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
            checksum = digest.hexdigest()
            if not size:
                # empty content is never filestore-backed (stays inline)
                tmp_path.unlink(missing_ok=True)
                return "", 0, checksum
            # Same path resolution (and same collision policy) as the buffered
            # writer; source_path keeps the check file-vs-file, unbuffered.
            fname, full_path_str = self._get_path(
                None, checksum, source_path=str(tmp_path)
            )
            full_path = Path(full_path_str)
            # Unlike the buffered writer, this one only learns its target after
            # hashing the whole stream, so the dedup test necessarily happens
            # here rather than before staging.
            if full_path.is_file():
                tmp_path.unlink(missing_ok=True)  # dedup hit: drop the temp
            else:
                # atomic within the filestore (same filesystem), like _file_write
                tmp_path.replace(full_path)
        # add fname to checklist, in case the transaction aborts
        self._mark_for_gc(fname)
        return fname, size, checksum

    @api.model
    def _check_admin_action(self) -> None:
        """Gate a whole-filestore maintenance action on administrator rights.

        The individual writes these actions perform are ACL-checked anyway; this
        fails fast, before a sweep over every attachment starts, and keeps one
        message for every such action.

        :raise AccessError: if the current user is not an administrator
        """
        if not self.env.is_admin():
            raise AccessError(_("Only administrators can execute this action."))

    @api.model
    def force_storage(self) -> None:
        """Force all attachments to be stored in the currently configured storage"""
        self._check_admin_action()

        # Migrate only binary attachments, including those linked to binary
        # fields (which are normally hidden by the _search override).
        self.with_context(skip_res_field_check=True).search(
            Domain.AND([self._get_storage_domain(), [("type", "=", "binary")]])
        )._migrate()

    @api.model
    def _full_path(self, path: str) -> str:
        path = self._sanitize_store_path(path)
        filestore = _resolve_filestore_root(self._filestore())
        full = (filestore / path).resolve()
        # Ensure the resolved path stays within the filestore (defense-in-depth).
        # is_relative_to() checks path components — startswith() would accept
        # sibling dirs like /data/odoo-evil for /data/odoo.
        if not full.is_relative_to(filestore):
            raise ValueError(f"Attachment path {path!r} escapes the filestore")
        return str(full)

    @api.model
    def _get_image_autoresize_config(self) -> tuple[list[str], int, int, int]:
        """Parse the image-autoresize system parameters, with guards.

        Misconfigured parameters must never crash an upload: an invalid
        resolution disables the resize, an invalid quality falls back to 80.

        :return: ``(subtypes, max_width, max_height, jpeg_quality)``;
            ``max_width``/``max_height`` are 0 when autoresize is disabled
        """
        ICP = self.env["ir.config_parameter"].sudo().get_param
        # strip(): whitespace in the param ("png, jpeg") must not silently
        # disable the resize for the affected subtypes
        subtypes = [
            subtype.strip()
            for subtype in ICP(
                "base.image_autoresize_extensions", "png,jpeg,bmp,tiff"
            ).split(",")
        ]
        # Can be set to 0 to skip the resize
        max_resolution = ICP("base.image_autoresize_max_px", "1920x1920")
        if not str2bool(max_resolution, True):
            return subtypes, 0, 0, 0
        try:
            max_width, max_height = map(int, max_resolution.split("x"))
        except ValueError:
            _logger.warning(
                "Invalid base.image_autoresize_max_px value: %r, skipping image resize",
                max_resolution,
            )
            return subtypes, 0, 0, 0
        quality = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("base.image_autoresize_quality", 80)
        )
        return subtypes, max_width, max_height, quality

    @api.model
    def _get_storage_domain(self) -> list[tuple[str, str, Any]]:
        """Return the domain matching attachments NOT in the current storage."""
        return self._storage_backend().migration_domain()

    @api.model
    def _get_path(
        self, bin_data: bytes | None, sha: str, *, source_path: str | None = None
    ) -> tuple[str, str]:
        """Return ``(fname, full_path)`` for storing content in the filestore.

        The single path-resolution point for BOTH filestore writers: it creates
        the shard directory and, for a collision-prone digest, performs the
        collision check. The streaming writer used to re-derive all three steps
        inline, so a deployment overriding this method silently kept the stock
        behaviour on streamed uploads.

        :param bin_data: the content to store, when the caller holds it in
            memory; ignored (and may be ``None``) if *source_path* is given
        :param str sha: the content digest, as produced by
            :meth:`_content_checksum`
        :param str source_path: path to the content already staged on disk.
            The streaming writer passes it so the collision check compares
            file-vs-file and never buffers either side.
        """
        fname = self._file_store_path(sha)
        full_path = Path(self._full_path(fname))
        full_path.parent.mkdir(exist_ok=True, parents=True)

        # on a dedup hit the stored file is read back to rule out a digest
        # collision serving wrong bytes. Governed by _verify_content_collision
        # (the read dominates large-file dedup).
        #
        # The gate is tested FIRST on purpose: both callers stat this path again
        # right after, to decide between "dedup hit" and "write the temp". With
        # the order reversed this method stat'd it too, on every single write,
        # even though the default digest (BLAKE3) disables the check entirely
        # and the answer was thrown away. Both operands are side-effect free, so
        # only the syscall count changes.
        if self._verify_content_collision() and full_path.is_file():
            same = (
                self._same_content_files(source_path, str(full_path))
                if source_path is not None
                else self._same_content(bin_data or b"", str(full_path))
            )
            if not same:
                raise UserError(_("The attachment collides with an existing file."))
        return fname, str(full_path)

    def _get_pdf_raw(self) -> bytes | None:
        """Return raw PDF bytes if this attachment is a binary PDF, else None."""
        self.ensure_one()
        if self.type != "binary" or not (self.mimetype or "").startswith(
            "application/pdf"
        ):
            return None
        return self.raw or None

    def _get_datas_related_values(
        self,
        data: bytes,
        mimetype: str,
        backend: AttachmentStorage | None = None,
        checksum: str | None = None,
    ) -> dict[str, Any]:
        """Derive the content columns for *data* AND persist its bytes.

        ``backend.write`` stores the payload and returns its store fragment
        (``store_fname``/``db_datas``) in one step. Callers must NOT persist the
        content again: the write is idempotent but a redundant call re-reads the
        whole stored file for the collision check (when it is enabled).
        """
        # Callers that already hashed *data* pass the checksum to skip a second
        # hash pass.
        if checksum is None:
            checksum = self._content_checksum(data)
        index_content = self._index(data, mimetype, checksum=checksum)
        # Content-path callers pass the operation's single write-side backend;
        # default-build one for external/override callers that omit it.
        if backend is None:
            backend = self._storage_backend()
        return {
            "file_size": len(data),
            "checksum": checksum,
            "index_content": index_content,
            # content location is backend policy; backend.write persists the
            # bytes and returns the fragment in the same step.
            **backend.write(data, checksum),
        }

    def _get_raw_access_token(self) -> str:
        """Return a scoped access token for the `raw` field, usable with
        `ir_binary._find_record` to bypass access rights.
        """
        self.ensure_one()
        return limited_field_access_token(self, "raw", scope="binary")

    @api.model
    def _get_serve_attachment(
        self, url: str, extra_domain: Any = None, order: str | None = None
    ) -> Self:
        domain = (
            Domain("type", "=", "binary")
            & Domain("url", "=", url)
            & Domain(extra_domain or [])
        )
        return self.search(domain, order=order, limit=1)

    @api.model
    def get_serving_groups(self) -> list[str]:
        """Groups allowed to create/write attachments servable via the http
        dispatch fallback (``type='binary'`` with ``url`` set).
        """
        return ["base.group_system"]

    def _content_for_rewrite(self, attach: Self, operation: str) -> bytes | None:
        """Return *attach*'s content, or ``None`` when rewriting it is unsafe.

        Shared data-loss guard for the two whole-filestore rewrites
        (:meth:`_migrate`, :meth:`_gc_rehash_legacy_keys`), which both read the
        content back and store it again. ``_file_read`` returns ``b""`` on a
        (possibly transient) read error; writing that back would blank the row
        AND let the GC reclaim its only copy. A row that reads empty while
        claiming a non-empty ``file_size`` is therefore skipped, and a later run
        retries it.

        :param str operation: what is being skipped, for the log line
        :return: the content, or ``None`` when the row must be left alone
        """
        raw = attach.raw
        if self._content_read_back_failed(
            raw,
            attach.file_size,
            attach.id,
            attach.store_fname,
            f"skipping {operation}",
        ):
            return None
        return raw

    def _rewrite_stored_content(
        self, attach: Self, values: dict[str, Any], old_fname: str | None
    ) -> None:
        """Point *attach* at freshly written content and release its old key.

        The ordering is the safety-critical half of both rewrites, and the
        reason they share it: the row must reference the new location BEFORE the
        old key becomes collectable, else the GC can reclaim content a committing
        ``store_fname`` still points at.
        """
        # internal metadata: bypass the public write override, as copy() does
        super(IrAttachment, attach.sudo()).write(values)
        attach.flush_recordset(
            ["store_fname", "db_datas", "checksum", "file_size", "index_content"]
        )
        if old_fname:
            # key-axis dispatch: the old content may live in another backend.
            attach._storage_delete(old_fname)

    def _rewritable_rows(
        self, rows: Self, operation: str
    ) -> Generator[tuple[int, Self, bytes]]:
        """Yield ``(index, attachment, content)`` for rows safe to rewrite.

        The shared preamble of the two whole-filestore rewrites (:meth:`_migrate`
        and :meth:`_gc_rehash_legacy_keys`): read each row's content back, skip
        the ones that read empty while claiming a size
        (:meth:`_content_for_rewrite` logs those), and drop the payload from the
        ORM cache once the caller is done with it so memory stays flat over a
        long run instead of growing O(total bytes) (P2-6). Only ``_migrate``
        used to do that last part; a large rehash backlog had the same problem.

        *index* is the 1-based position in *rows* — including skipped rows, so
        progress logging and commit cadence stay tied to the work actually
        enumerated rather than to how many rows happened to be readable.
        """
        for index, attach in enumerate(rows, 1):
            raw = self._content_for_rewrite(attach, operation)
            if raw is None:
                continue
            yield index, attach, raw
            attach.invalidate_recordset()

    def _migrate(self) -> None:
        record_count = len(self)
        backend = self._storage_backend()
        storage = self._storage().upper()
        _logger.info("Migrating %d attachments to %s", record_count, storage)
        # Commit batch-by-batch on live runs: a filestore-wide force_storage
        # otherwise holds one giant transaction (row locks, WAL bloat, restart
        # on crash). Re-runs are idempotent (the domain skips migrated rows).
        # Tests run in a savepoint, where commit is forbidden.
        can_commit = not (modules.module.current_test or config["test_enable"])
        for index, attach, raw in self._rewritable_rows(self, "migration"):
            if index % 100 == 0 or index == record_count:
                _logger.info(
                    "Migrating attachment %d/%d to %s", index, record_count, storage
                )
            # A location migration doesn't change the bytes: reuse the derived
            # checksum/file_size/index_content and move only the store fragment,
            # skipping the re-hash and re-index (P1). Escape-hatch db_datas
            # rows never had this metadata stamped, so fall back to full derivation.
            # (This is exactly what a REHASH must not do — see
            # _gc_rehash_legacy_keys, whose whole purpose is to change the digest.)
            reuse = bool(attach.checksum) and attach.file_size == len(raw)
            checksum = attach.checksum if reuse else self._content_checksum(raw)
            # Both branches persist content into the target backend and return
            # its store fragment, written before the flush inside the helper, so
            # the row never references a not-yet-written file.
            self._rewrite_stored_content(
                attach,
                backend.write(raw, checksum)
                if reuse
                else self._get_datas_related_values(raw, attach.mimetype, backend),
                attach.store_fname,
            )
            if can_commit and index % 100 == 0:
                self.env.cr.commit()

    def _mimetype_from_values(self, values: dict[str, Any]) -> str:
        """Guess the mimetype from create/write values.

        :param dict values: create or write values of an attachment
        :return: the mimetype, ``application/octet-stream`` by default
        :rtype: str
        """
        mimetype = None
        if values.get("mimetype"):
            mimetype = values["mimetype"]
        if not mimetype and values.get("name"):
            mimetype = mimetypes.guess_type(values["name"])[0]
        if not mimetype and values.get("url"):
            mimetype = mimetypes.guess_type(values["url"].split("?")[0])[0]
        if not mimetype or mimetype == "application/octet-stream":
            raw = None
            if "raw" in values and values["raw"] is not None:
                raw = values["raw"]
            elif values.get("datas"):
                # Unreachable via create/write (they decode upstream), but direct
                # callers of this hook get the same clean UserError.
                raw = self._decode_datas(values["datas"])
            if raw:
                mimetype = guess_mimetype(raw)
        return (mimetype and mimetype.lower()) or "application/octet-stream"

    def _read_prefix(self, size: int | None = None) -> bytes:
        """Return up to *size* bytes of this attachment's content (all if ``None``).

        The single partial-read primitive. It resolves the three content
        locations — keyed backend, inline ``db_datas``, addon-static ``url`` —
        without materializing more than *size* bytes.
        :class:`~odoo.http.Stream` cannot express a partial read, so callers
        needing only a head (text thumbnails, sniffers) used to re-implement
        this triage against ``store_fname``/``db_datas``/``url`` themselves.

        ``bin_size`` is neutralized on purpose: under it a stored binary column
        reads back as ``pg_size_pretty(length(...))``, so a caller in a
        ``bin_size`` context would otherwise receive a human size string
        (``b"1.5 kB"``) and mistake it for content.

        :param size: maximum number of bytes to read; ``None`` reads it all
        :return: the content prefix, or ``b""`` when there is nothing readable
        """
        self.ensure_one()
        stored = self._stored_content(size)
        if stored is not None:
            return stored
        if static_path := self._static_file_path():
            with file_open(static_path, "rb") as file:
                return file.read(size)
        return b""

    def _stored_content(self, size: int | None = None) -> bytes | None:
        """Return up to *size* bytes of the content THIS row stores itself.

        The keyed-backend / inline-``db_datas`` triage, shared by
        :meth:`_compute_raw` and :meth:`_read_prefix` — which differ only in what
        they do when there is nothing stored, so that decision is left to them.
        :meth:`_to_http_stream` runs the same triage a third time, in terms of
        streams rather than bytes.

        ``bin_size`` is neutralized on purpose: under it a stored binary column
        reads back as ``pg_size_pretty(length(...))``, so a caller in a
        ``bin_size`` context would otherwise receive a human size string
        (``b"1.5 kB"``) and mistake it for content. Computes inherit that
        neutralization from ``Binary.compute_value``; a plain method call does
        not, which is why it is spelled out here.

        :param size: maximum number of bytes to read; ``None`` reads it all
        :return: the content, or ``None`` when this row stores none (no store
            key and no inline data)
        """
        self.ensure_one()
        if self.store_fname:
            # key-axis dispatch: content follows its store key, not the
            # configured location (plain keys → local filestore)
            data = self._backend_for_key(self.store_fname).read(self.store_fname, size)
            self._content_read_back_failed(
                data, self.file_size, self.id, self.store_fname, "serving empty bytes"
            )
            return data
        # see the bin_size note above: read the column, never its size
        attach = self.with_context(bin_size=False, bin_size_db_datas=False)
        if db_datas := attach.db_datas:
            return db_datas if size is None else db_datas[:size]
        return None

    @api.model
    def _content_read_back_failed(
        self,
        data: bytes,
        expected_size: int,
        att_id: Any,
        key: Any,
        action: str,
    ) -> bool:
        """Whether a read came back empty for a row that claims content.

        A store key is only ever set for NON-empty content, so an empty read
        means the stored file is missing or unreadable (the backend swallows the
        I/O error). The three readers that must not mistake that for
        "legitimately empty" — serving ``raw``, indexing a streamed upload,
        rewriting a row — each spelled the test out themselves, with three
        different log levels for the same event. The predicate and the log line
        live here; what to do about it stays at the call site.

        :param str action: what the caller does about it, for the log line
        :return: whether the read must be treated as a failure
        """
        if data or not expected_size:
            return False
        _logger.error(
            "Unreadable stored content for attachment %s (store_fname=%s); %s",
            att_id,
            key,
            action,
        )
        return True

    def _static_file_path(self) -> str | None:
        """Resolve this row's ``url`` to an addon static file, if it names one.

        A ``url`` targeting an addon file is a resource path rather than a
        remote link, and both readers that honour it (:meth:`_read_prefix` and
        :meth:`_to_http_stream`) must resolve it the same way — including the
        ``request`` guard, since neither runs only under HTTP (cron, report
        rendering).

        :return: the static file path, or ``None`` when the url names no addon file
        """
        self.ensure_one()
        if not self.url:
            return None
        host = request.httprequest.environ.get("HTTP_HOST", "") if request else ""
        return root.get_static_file(self.url, host=host)

    @api.model
    def _streams_equal(self, stream_a: Any, stream_b: Any) -> bool:
        """Return whether two binary streams yield identical bytes.

        The one chunked comparison loop behind :meth:`_same_content` and
        :meth:`_same_content_files`, which differed only in where each side's
        bytes came from. Neither side is ever fully buffered.
        """
        while True:
            chunk_a = stream_a.read(self._COMPARE_BLOCK_SIZE)
            if chunk_a != stream_b.read(self._COMPARE_BLOCK_SIZE):
                return False
            if not chunk_a:
                return True

    @api.model
    def _same_as_file(self, source: Any, source_size: int, filepath: str) -> bool:
        """Return whether *filepath* holds exactly what *source* yields.

        The size-reject-then-stream-compare shared by :meth:`_same_content` and
        :meth:`_same_content_files`, which differ only in where the left-hand
        bytes come from. Neither side is ever fully buffered.

        :param source: an already-open binary stream for the left-hand side
        :param int source_size: its total length, for the fast reject
        :param str filepath: path to the existing file (caller guarantees it exists)
        """
        # Fast reject on size (stat() is cheaper than reading the whole file).
        if Path(filepath).stat().st_size != source_size:
            return False
        with Path(filepath).open("rb") as fd:
            return self._streams_equal(source, fd)

    @api.model
    def _same_content(self, bin_data: bytes, filepath: str) -> bool:
        """Return whether *filepath* holds exactly *bin_data*.

        :param str filepath: path to the existing file (caller guarantees it exists)
        """
        with io.BytesIO(bin_data) as buf:
            return self._same_as_file(buf, len(bin_data), filepath)

    @api.model
    def _same_content_files(self, path_a: str, path_b: str) -> bool:
        """Return whether two files hold identical bytes (streamed compare).

        File-vs-file counterpart of :meth:`_same_content`, used by
        :meth:`_file_write_stream` so a dedup collision check never buffers
        either side.
        """
        with Path(path_a).open("rb") as fa:
            return self._same_as_file(fa, Path(path_a).stat().st_size, path_b)

    @api.model
    def _sanitize_store_path(self, path: str) -> str:
        """Neutralize traversal vectors in a store path (dots, colons, leading/trailing separators)."""
        return re.sub(r"[.:]", "", path).strip("/\\")

    def _set_attachment_data(self, asbytes: Callable[[Any], bytes]) -> None:
        # Re-check serving permission on content changes too (IRA-P1-1): `write`
        # only re-checks on url/type change, but swapping a served attachment's
        # content changes what _serve_fallback hands out. Both content paths
        # converge here (the inverse writes as sudo, bypassing `write`).
        self._check_serving_attachments()
        old_fnames = []
        wrote_content = False
        backend = self._storage_backend()
        # Single-slot memo of the previous record's derived values: a
        # multi-record `write({'raw': X})` hands every record the same cached
        # bytes object, so re-hashing/re-indexing/re-writing it per row is waste
        # (the memo also persists each distinct payload once). One slot, not a
        # map keyed on id(bin_data): holding the single reference keeps the
        # identity check sound, and the base64 path (a distinct object per
        # record, never a hit) is not pinned into O(total bytes).
        memo_key: tuple[bytes, str] | None = None  # (bin_data, mimetype)
        memo_vals: dict[str, Any] = {}

        for attach in self:
            # compute the fields that depend on datas
            bin_data = asbytes(attach)
            if memo_key and memo_key[0] is bin_data and memo_key[1] == attach.mimetype:
                vals = memo_vals
            else:
                vals = self._get_datas_related_values(
                    bin_data, attach.mimetype, backend
                )
                memo_key, memo_vals = (bin_data, attach.mimetype), vals

            # take the current store key to possibly garbage-collect it
            if attach.store_fname:
                old_fnames.append(attach.store_fname)

            # write as superuser, as user probably does not have write access
            super(IrAttachment, attach.sudo()).write(vals)

            if bin_data:
                # Content was already persisted by _get_datas_related_values.
                # Writing as we go (releasing each bin_data) keeps peak memory
                # flat; safe because the flush below precedes any old-key delete.
                wrote_content = True

        if old_fnames or wrote_content:
            # flush so rows reference the new content before any old key is
            # marked for deletion (prevents GC'ing in-use content mid-transaction)
            self.flush_recordset(["checksum", "store_fname"])
        for fname in old_fnames:
            # key-axis dispatch: old content may live in another backend, and
            # under db location too (the old use_filestore gate leaked those).
            self._storage_delete(fname)

    @api.model
    def _storage(self) -> str:
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("ir_attachment.location", "file")
        )

    @api.model
    def _storage_backend(self) -> AttachmentStorage:
        """Return the write-side backend for the configured storage location.

        Decides where NEW content goes; existing content follows its store key
        (:meth:`_backend_for_key`), so the two can differ (a location switch
        does not migrate rows). Unknown locations fall back to :class:`FileStorage`.
        """
        backend_cls = STORAGE_BACKENDS.get(self._storage(), FileStorage)
        return backend_cls(self.env)

    @api.model
    def _storage_delete(self, fname: str) -> None:
        """Schedule deletion of the content at *fname* in its owning backend.

        Key-axis dispatch: the key may live in a backend other than the
        configured one (a location switch does not migrate rows).
        """
        self._backend_for_key(fname).delete(fname)

    @api.model
    def _storage_delete_multi(self, fnames: Collection[str]) -> None:
        """Batch counterpart of :meth:`_storage_delete`.

        Scheme-keyed content (``s3://...``) dispatches per key; plain filestore
        keys — the common case — go through :meth:`_file_delete_multi` in one
        grouped pass, skipping the per-key ``FileStorage.delete`` indirection but
        NOT the local-filestore override point (this used to call
        :meth:`_mark_for_gc_multi` directly, which bypassed it).
        """
        plain_fnames = []
        for fname in fnames:
            if "://" in fname:
                self._backend_for_key(fname).delete(fname)
            else:
                plain_fnames.append(fname)
        if plain_fnames:
            self._file_delete_multi(plain_fnames)

    @api.model
    def _verify_content_collision(self) -> bool:
        """Whether to byte-compare the stored file against new content on dedup.

        On a dedup hit, :meth:`_get_path` re-reads the whole stored file to rule
        out a digest collision serving wrong bytes — a cost dominating
        large-file dedup.

        The default follows the digest in use, because the check only ever
        mitigated a *broken* one: sha1 has practical chosen-prefix collisions,
        so an attacker who can upload two crafted files can make one serve the
        other's bytes — hence verify.  BLAKE3 has no such weakness, and the
        re-read buys nothing there beyond detecting filestore corruption, which
        is not this method's job.  Either way
        ``ir_attachment.verify_content_collision`` wins when set, so an operator
        can force the read back on (or off) regardless of algorithm.

        :return: whether to re-read and byte-compare on a dedup hit
        """
        default = ALGO_TAG == "s1"
        return str2bool(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("ir_attachment.verify_content_collision", str(default)),
            default,
        )

    def _postprocess_contents(self, values: dict[str, Any]) -> dict[str, Any]:
        # Reuse the mimetype _check_contents already resolved; sniff only when
        # invoked standalone, skipping a redundant _mimetype_from_values pass.
        mimetype = values.get("mimetype") or self._mimetype_from_values(values)
        values["mimetype"] = mimetype
        maintype, _, subtype = mimetype.partition("/")
        if maintype != "image" or not (values.get("datas") or values.get("raw")):
            return values
        subtypes, max_width, max_height, quality = self._get_image_autoresize_config()
        if subtype not in subtypes or not max_width:
            return values

        is_raw = bool(values.get("raw"))
        try:
            data = values["raw"] if is_raw else base64.b64decode(values["datas"])
            img = image.ImageProcess(data, verify_resolution=False)
            if not img.image:
                _logger.info("Post processing ignored : Empty source, SVG, or WEBP")
                return values
            width, height = img.image.size
            if width <= max_width and height <= max_height:
                return values
            img = img.resize(max_width, max_height)
            # quality applies to JPEG only: do not affect PNGs color palette
            image_data = img.image_quality(quality=quality if subtype == "jpeg" else 0)
            if is_raw:
                values["raw"] = image_data
            else:
                values["datas"] = base64.b64encode(image_data)
        except (UserError, OSError, image.Image.DecompressionBombError) as e:
            # Autoresize is best-effort and must never 500 an upload. Besides the
            # UserError from ImageProcess.__init__, resize()/image_quality() leak
            # PIL-native exceptions: OSError on a truncated image, and
            # DecompressionBombError on an oversized one during the
            # verify_resolution=False decode. Swallow all and keep the original
            # bytes; the payload is never fully decoded, so memory stays bounded.
            _logger.info("Post processing ignored : %s", e)
        return values

    @api.model
    def _index(
        self, bin_data: bytes, file_type: str, checksum: str | None = None
    ) -> str | None:
        """Extract the searchable text content of *bin_data* (text types only).

        Python implementation of the unix command ``strings``.

        :param checksum: unused here; hook parameter for caching overrides
        :return: the index content, or ``None`` for non-text content
        """
        # compute index_content only for text type
        if file_type and file_type.startswith("text/"):
            # Decode as UTF-8, then keep runs of printable characters. Scanning
            # the decoded TEXT (not raw bytes) keeps accented/non-Latin words
            # whole: the old byte-class [\x20-\x7E] split every multi-byte char,
            # shredding e.g. "configuración". Identical to the old output for
            # pure-ASCII content.
            text = bin_data[: self._INDEX_MAX_BYTES].decode("utf-8", errors="ignore")
            words = re.findall(r"[^\x00-\x1f\x7f-\x9f]{4,}", text)
            return "\n".join(words)
        return None

    @api.model
    def _index_read_size(self, mimetype: str) -> int | None:
        """How many bytes of stored content to read back to feed :meth:`_index`.

        Used by the streaming create path (:meth:`_create_from_stream`), which
        wrote the payload without buffering:

        * ``0`` — skip the read (nothing this backend indexes);
        * a positive int — read a bounded prefix;
        * ``None`` — read the whole stored content.

        Base indexes only ``text/*`` (capped at ``_INDEX_MAX_BYTES``), so every
        other mimetype reads NOTHING — avoiding a wasted prefix read on every
        binary upload. Overrides that parse more (``attachment_indexation``)
        widen this; returning ``None`` there keeps them consistent with the
        buffered path, which gets the full content.
        """
        if mimetype and mimetype.startswith("text/"):
            return self._INDEX_MAX_BYTES
        return 0

    def _inaccessible_comodel_records(
        self, model_and_ids: dict[str, Collection[int]], operation: str
    ) -> Generator[tuple[str, int]]:
        # check access rights on the records
        if self.env.su:
            return
        for res_model, res_ids in model_and_ids.items():
            res_ids = OrderedSet(filter(None, res_ids))
            if not res_model or not res_ids:
                # nothing to check
                continue
            # forbid access to attachments linked to removed models as we do not
            # know what permissions should be checked
            if res_model not in self.env:
                for res_id in res_ids:
                    yield res_model, res_id
                continue
            if res_model == "res.users" and self.env.uid in res_ids:
                # A user cannot write on itself despite writable fields (e.g. its
                # own image signature), so _filtered_access would drop the user's
                # OWN record. Exclude just that record rather than the whole batch
                # — a batch mixing self with another user's row otherwise wrongly
                # denied the self record too (IRA review #4).
                res_ids = OrderedSet(rid for rid in res_ids if rid != self.env.uid)
                if not res_ids:
                    continue
            records = self.env[res_model].browse(res_ids)
            try:
                records = records._filtered_access(operation)
            except MissingError:
                records = records.exists()._filtered_access(operation)
            res_ids.difference_update(records._ids)
            for res_id in res_ids:
                yield res_model, res_id

    @api.model
    def _search_models_security_domain(
        self,
        domain: Domain,
        res_model_names: Collection[Any],
        disable_binary_fields_attachments: bool,
    ) -> Domain:
        """Build the OR of per-comodel access subdomains for *res_model_names*.

        Per linked model, an attachment is reachable when its ``res_id`` record
        is accessible (a subquery on the comodel's ``_search``) and, for a
        non-system user, when ``res_field`` names a readable binary/relational
        field. Only the small-model path uses this
        (``len <= _SEARCH_MODEL_DOMAIN_LIMIT``); the rest go through
        :meth:`_fetch_accessible_ids`.

        :param disable_binary_fields_attachments: whether ``res_field`` is
            already forced to ``False`` upstream (skips the field-ACL clause)
        :return: the OR of the per-model subdomains (``Domain.FALSE`` if none)
        """
        env = self.with_context(active_test=False).env
        models_domain = Domain.FALSE
        for res_model_name in res_model_names:
            if (comodel := env.get(res_model_name)) is None:
                continue
            codomain = Domain("res_model", "=", comodel._name)
            comodel_res_ids = condition_values(
                self,
                "res_id",
                domain.map_conditions(
                    # `codomain=codomain` binds this iteration's value. DEFENSIVE
                    # only: map_conditions is eager today, so the late-binding
                    # pitfall can't bite; the default arg keeps the closure correct
                    # should it ever become lazy. See IRA-M1.
                    lambda cond, codomain=codomain: (
                        codomain & cond if cond.field_expr == "res_model" else cond
                    )
                ),
            )
            query = comodel._search(
                Domain("id", "in", comodel_res_ids) if comodel_res_ids else Domain.TRUE
            )
            if query.is_empty():
                continue
            if query.where_clause:
                codomain &= Domain("res_id", "in", query)
            if not disable_binary_fields_attachments and not self.env.is_system():
                accessible_fields = [
                    field.name
                    for field in comodel._fields.values()
                    if (
                        field.type == "binary"
                        or (field.relational and field.comodel_name == self._name)
                    )
                    and comodel._has_field_access(field, "read")
                ]
                accessible_fields.append(False)
                codomain &= Domain("res_field", "in", accessible_fields)
            models_domain |= codomain
        return models_domain

    def _fetch_accessible_ids(
        self, domain: Domain, order: str | None, bound: int | None
    ) -> list[int]:
        """Collect ids readable by the current user, fetching by batches.

        With no ``order``, batches advance by keyset pagination on a
        deterministic order — constant cost per batch, where OFFSET re-scans
        skipped rows and made the scan quadratic (IRA-B5). A caller ``order``
        keeps OFFSET batching but is made total by appending the unique ``id``,
        else ties across a batch boundary could be skipped or duplicated — an
        access-control hazard, not just a perf one.

        :param bound: stop once this many ids are collected (None: collect all)
        :return: the accessible ids
        """
        keyset = None
        if not order:
            if bound is None:
                # mirror the model default order (previous behavior)
                order = "id desc"

                def keyset(last: Self) -> Domain:
                    return Domain("id", "<", last.id)
            else:
                # By default, order by model to batch access checks.
                order = "res_model nulls first, id"

                def keyset(last: Self) -> Domain:
                    if last.res_model:
                        return (
                            Domain("res_model", "=", last.res_model)
                            & Domain("id", ">", last.id)
                        ) | Domain("res_model", ">", last.res_model)
                    # NULLs sort first: rest of the null group, then the rest
                    return (
                        Domain("res_model", "=", False) & Domain("id", ">", last.id)
                    ) | Domain("res_model", "!=", False)
        else:
            # A caller order may have no unique tiebreaker; OFFSET over a
            # non-total order can skip/duplicate rows across batches (PostgreSQL
            # may order ties differently per query). Append `id` for a total,
            # stable sort. `keyset` stays None: an arbitrary sort has no seek
            # predicate, so this path keeps OFFSET batching.
            order = f"{order}, id"

        result: list[int] = []
        sub_offset = 0
        batch_domain = domain
        while bound is None or len(result) < bound:
            records = (
                self.sudo()
                .with_context(active_test=False)
                .search_fetch(
                    batch_domain,
                    SECURITY_FIELDS,
                    offset=sub_offset,
                    limit=PREFETCH_MAX,
                    order=order,
                )
                .sudo(False)
            )
            result.extend(records._filtered_access("read")._ids)
            if len(records) < PREFETCH_MAX:
                # There are no more records
                break
            if keyset is not None:
                # sudo: _check_access invalidated the security fields of
                # forbidden rows (cache-pollution guard), and the keyset
                # anchor may be one of them
                batch_domain = domain & keyset(records.sudo()[-1])
            else:
                sub_offset += PREFETCH_MAX
        return result

    def _post_add_create(self, **kwargs: Any) -> None:
        """Hook called after an attachment is uploaded. Overridden by mail, account, etc."""

    def generate_access_token(self) -> list[str]:
        tokens = []
        new_tokens = {}  # {id: token} for the records that lack one
        for attachment in self:
            if attachment.access_token:
                tokens.append(attachment.access_token)
                continue
            token = self._generate_access_token()
            new_tokens[attachment.id] = token
            tokens.append(token)
        # Write through super(): an access_token write can't change serving
        # eligibility or content, so re-entering the public write() override is
        # pure overhead. super().write still enforces the write and field-group
        # ACLs. Tokens are unique, so the writes can't collapse into one UPDATE.
        for attachment in self.browse(new_tokens):
            super(IrAttachment, attachment).write(
                {"access_token": new_tokens[attachment.id]}
            )
        return tokens

    @api.model
    def create_unique(self, values_list: list[dict[str, Any]]) -> list[int]:
        """Create attachments, deduplicating by checksum/size/mimetype.

        Accepts content as base64 ``datas`` or ``raw`` like :meth:`create`
        (``raw`` wins by key presence). The create() content pipeline runs ONCE
        per value here, so the dedup key is the checksum of the bytes that will
        actually be stored — hashing pre-pipeline bytes made an autoresized
        image miss its stored copy and create a duplicate row. The pipeline is
        cheap for common inputs (header-only parse; full decode only for an
        oversized image, whose resized bytes create() then reuses).

        Values carrying no content key at all are never deduplicated: like
        :meth:`create`, they keep ``checksum = False`` and any ``db_datas``
        passthrough they were given.

        :raise UserError: if a value is not base64-encoded or omits ``mimetype``

        .. note::
            The dedup search runs as ``sudo()`` to match a filestore-shared file
            across companies, so the returned id may belong to another company.
            Reading it is still ACL-gated, so no content leaks (IRA-C2).
        """
        # Phase 1: normalize content (raw|datas), apply the create() content
        # pipeline, and key the dedup on the FINAL (post-pipeline) checksum.
        # `_normalize_content_vals` is shared with create()/write() on purpose:
        # the hand-rolled copy this replaced set `raw = b""` even for vals
        # carrying NO content key, which stamped the digest of b"" over a
        # caller's `db_datas` and erased it (the IRA-R1/IRA-C4 invariant).
        entries: list[tuple[dict, tuple[str, int, str] | None]] = []
        for values in values_list:
            if "mimetype" not in values:
                raise UserError(_("Attachment is missing its mimetype."))
            # copy: _normalize_content_vals mutates in place and the caller's
            # dicts must not be touched
            vals = dict(values)
            has_content = self._normalize_content_vals(vals)
            vals = self._check_contents(vals)
            # Content-less vals have nothing to deduplicate on: create() leaves
            # them with `checksum = False`, so keying them on the digest of b""
            # would collapse unrelated rows (a `db_datas` passthrough, a bare
            # url row) onto a single id. They are always created.
            key = None
            if has_content:
                raw = vals["raw"]
                key = (self._content_checksum(raw), len(raw), vals["mimetype"])
            entries.append((vals, key))

        # Phase 2: find one existing id per (checksum, file_size, mimetype).
        # Aggregate instead of materializing every row sharing a checksum (which
        # was O(rows-with-that-checksum) on a hot file). id:max reproduces the
        # old "newest match" (default `id desc` + setdefault-first).
        # skip_res_field_check: also match binary-field-backing attachments,
        # which _search hides by default.
        all_checksums = list({key[0] for _vals, key in entries if key})
        existing_by_key: dict[tuple, int] = {}
        if all_checksums:
            for checksum, file_size, mimetype, att_id in (
                self.sudo()
                .with_context(skip_res_field_check=True)
                ._read_group(
                    [("checksum", "in", all_checksums)],
                    groupby=["checksum", "file_size", "mimetype"],
                    aggregates=["id:max"],
                )
            ):
                existing_by_key[checksum, file_size, mimetype] = att_id

        # Phase 3: batch-create the misses (in-batch dupes → first occurrence),
        # then resolve ids in input order. The pipeline ran in phase 1, so skip
        # a second autoresize pass.
        to_create = []
        new_index_by_key: dict[tuple, int] = {}
        # index into `created` for the entries that bypass dedup (key is None)
        own_indexes: list[int | None] = []
        for vals, key in entries:
            if key is None:
                own_indexes.append(len(to_create))
                to_create.append(vals)
                continue
            own_indexes.append(None)
            if key not in existing_by_key and key not in new_index_by_key:
                new_index_by_key[key] = len(to_create)
                to_create.append(vals)
        created = (
            self.with_context(image_no_postprocess=True).create(to_create)
            if to_create
            else self.browse()
        )
        return [
            (
                created[own_index].id
                if own_index is not None
                else existing
                if (existing := existing_by_key.get(key))
                else created[new_index_by_key[key]].id
            )
            for (_vals, key), own_index in zip(entries, own_indexes, strict=True)
        ]

    def _generate_access_token(self) -> str:
        return str(uuid.uuid4())

    @api.model
    def action_get(self) -> dict[str, Any]:
        return self.env["ir.actions.act_window"]._for_xml_id("base.action_attachment")

    def _from_request_file(self, file: Any, *, mimetype: str, **vals: Any) -> Self:
        """Create an attachment out of a request file.

        :param file: the request file
        :param str mimetype: one of —
            * ``"TRUST"`` — use the request file's mimetype/extension unverified;
            * ``"GUESS"`` — detect from content, appending the extension unless
              the filename already has a valid one;
            * ``"{type}/{subtype}"`` — force this mimetype, appending its
              extension unless the filename already has a valid one.
        """
        # dispatch the three mimetype modes: TRUST / GUESS / explicit (IRA-T2)
        if mimetype == "TRUST":
            mimetype = file.content_type
            filename = file.filename
        elif mimetype == "GUESS":
            head = file.read(MIMETYPE_HEAD_SIZE)
            file.seek(-len(head), 1)  # rewind
            mimetype = guess_mimetype(head)
            filename = fix_filename_extension(file.filename, mimetype)
            if mimetype in ("application/zip", *_olecf_mimetypes):
                # Re-guess from the (potentially corrected) filename to get a
                # more specific type (e.g. .docx → openxmlformats).  Keep the
                # content-detected mimetype as fallback for extensionless files.
                mimetype = mimetypes.guess_type(filename)[0] or mimetype
        elif "/" in mimetype and all(mimetype.split("/", 1)):
            # an explicit "{type}/{subtype}" with both halves non-empty
            filename = fix_filename_extension(file.filename, mimetype)
        else:
            raise ValueError(f"{mimetype=}")

        if self._should_stream_upload(mimetype):
            # Stream straight to storage: werkzeug has already spooled the upload
            # to a temp file, so file.read() would only copy disk -> RAM.
            return self._create_from_stream(
                file, name=filename, mimetype=mimetype, **vals
            )
        return self.create(
            {
                "name": filename,
                "type": "binary",
                "raw": file.read(),  # image autoresize needs the full payload
                "mimetype": mimetype,
                **vals,
            }
        )

    def _create_from_stream(
        self, fileobj: Any, *, name: str, mimetype: str, **vals: Any
    ) -> Self:
        """Create a binary attachment by streaming *fileobj* into storage.

        The row is created first (access checks, post-add hooks) WITHOUT
        content, then the payload is streamed in and the derived metadata
        written back internally (like :meth:`copy`). Peak memory stays O(chunk).

        :param fileobj: a binary file-like supporting ``read(size)``
        """
        record = self.create(
            {"name": name, "type": "binary", "mimetype": mimetype, **vals}
        )
        # Resolve the write-side backend once and stream the payload into it.
        store_values = self._storage_backend().write_stream(fileobj)
        # index_content from the stored content. _index_read_size decides how
        # much to read back for THIS mimetype: 0 skips it (common binary case,
        # no wasted round-trip), a prefix for text, or the whole file for
        # document-parsing backends. The checksum lets them share their index
        # cache with the buffered path.
        read_size = self._index_read_size(record.mimetype)
        index_content = None
        if read_size != 0:
            content = b""
            readable = True
            if store_values.get("store_fname"):
                content = self._backend_for_key(store_values["store_fname"]).read(
                    store_values["store_fname"], read_size
                )
                # Don't stamp an index built from the wrong bytes.
                if self._content_read_back_failed(
                    content,
                    store_values["file_size"],
                    record.id,
                    store_values["store_fname"],
                    "skipping index extraction",
                ):
                    readable = False
            elif store_values.get("db_datas"):
                db_datas = store_values["db_datas"] or b""
                content = db_datas if read_size is None else db_datas[:read_size]
            if readable:
                index_content = self._index(
                    content, record.mimetype, checksum=store_values.get("checksum")
                )
        store_values["index_content"] = index_content
        # Content metadata is internal: bypass the public write override, exactly
        # as copy() does for relinked content.
        super(IrAttachment, record.sudo()).write(store_values)
        # The content of a (possibly served) binary changed; re-check serving
        # permission, which the super() write bypassed (IRA-P1-1).
        record._check_serving_attachments()
        return record

    def _to_http_stream(self) -> Stream:
        """Create a :class:`~Stream` from an ir.attachment record."""
        self.ensure_one()

        stream = Stream(
            mimetype=self.mimetype,
            download_name=self.name,
            etag=self.checksum,
            public=self.public,
        )

        if self.store_fname:
            # key-axis dispatch: content follows its store key, not the
            # configured location (still streams from disk after a switch to db)
            return self._backend_for_key(self.store_fname).to_stream(self, stream)

        if self.db_datas:
            stream.type = "data"
            stream.data = self.raw
            stream.last_modified = self.write_date
            stream.size = len(stream.data)

        elif self.url:
            # A URL targeting an addon file is a resource path — stream it right
            # away (same resolution as _read_prefix).
            if static_path := self._static_file_path():
                stream = Stream.from_path(static_path, public=True)
            else:
                stream.type = "url"
                stream.url = self.url

        else:
            stream.type = "data"
            stream.data = b""
            stream.size = 0

        return stream

    def _migrate_remote_to_local(self) -> bool:
        """Hook: make the attachment's content locally available.

        Storage modules (e.g. ``cloud_storage``) override this to download the
        remote payload and convert the record to ``type='binary'``. A plain
        ``url`` attachment has no retrievable payload — an expected condition,
        hence a ``False`` return rather than an error.

        :return: whether the attachment now holds local binary content
        """
        self.ensure_one()
        return self.type == "binary"

    # ------------------------------------------------------------
    # GC METHODS
    # ------------------------------------------------------------

    @api.autovacuum
    def _audit_url_attachments(self) -> None:
        """Defense-in-depth observation for ``ir.http._serve_fallback``.

        That fallback serves any ``type='binary'`` attachment whose ``url``
        matches the request path under ``sudo()``. A ``url``-set,
        ``public=False`` row is an oddity (served attachments are normally
        public) suggesting a misconfiguration or a controller leaking input
        into ``vals``. ``_check_serving_attachments`` blocks non-admin writes;
        this catches what slips through ``sudo()`` bypasses. An observation, not
        a block.

        Each row warns once when first seen, then logs at INFO while unresolved
        (re-warning nightly only trains operators to ignore it); seen ids persist
        in ``ir_attachment.url_audit_seen``. Only the lowest-id window
        (:attr:`_URL_AUDIT_WINDOW`) is tracked, but the logged ``total`` reflects
        the true burst size.
        """
        domain = Domain(
            [
                ("type", "=", "binary"),
                ("url", "!=", False),
                ("public", "=", False),
            ]
        )
        # Report the true total but only track the lowest-id window.
        total = self.sudo().search_count(domain)
        if not total:
            return
        suspicious = self.sudo().search(
            domain, order="id", limit=self._URL_AUDIT_WINDOW
        )
        ICP = self.env["ir.config_parameter"].sudo()
        param = "ir_attachment.url_audit_seen"
        seen = {
            int(token)
            for token in ICP.get_param(param, "").split(",")
            if token.strip().isdigit()
        }
        new = suspicious.filtered(lambda a: a.id not in seen)
        if new:
            _logger.warning(
                "Found %d non-public binary attachment(s) with `url` set "
                "(showing %d); review that these are intended to be served via "
                "ir.http._serve_fallback. First URLs: %s",
                total,
                len(new),
                new.mapped("url"),
            )
        else:
            _logger.info(
                "%d previously reported non-public binary attachment(s) with "
                "`url` set remain unresolved (showing %d).",
                total,
                len(suspicious),
            )
        current = set(suspicious.ids)
        if current != seen:
            ICP.set_param(param, ",".join(map(str, sorted(current))))

    @api.autovacuum
    def _gc_file_store(self) -> bool | None:
        """Garbage-collect unreferenced content in every storage backend.

        ALL registered backends run, not only the configured one: content
        follows its store key, so a switched-away backend still owns keys to
        collect (else its checklist stays unswept while ``location='db'``).

        :return: ``False`` if any backend skipped its run (e.g. lock unavailable,
            retried next autovacuum), else ``None``
        """
        # snapshot the registry before any backend commits; the loop issues no
        # DB statement, so each backend can make LOCK its transaction's first.
        skipped = False
        for backend_cls in tuple(STORAGE_BACKENDS.values()):
            if backend_cls(self.env).autovacuum() is False:
                skipped = True
        return False if skipped else None

    @api.autovacuum
    def _gc_rehash_legacy_keys(self, limit: int | None = None) -> tuple[int, int]:
        """Re-key a bounded batch of rows still stored under a legacy digest.

        :meth:`_file_store_path` tags store keys with the digest that produced
        them, so a switch of algorithm is additive: old keys keep resolving and
        nothing is rewritten.  The cost is that the two layouts dedup
        independently — content stored under the old digest is written again
        under the new one the first time it is re-uploaded — and that legacy
        content only converges when its row happens to be rewritten.

        This pass converges the rest, deliberately as an **opt-in trickle**
        rather than a filestore-wide migration: set
        ``ir_attachment.rehash_legacy_keys_limit`` to the number of rows one
        autovacuum run may re-key.  Unset (or ``0``) is a no-op, which is the
        default — an operator who is happy with mixed layouts pays nothing, and
        nobody gets a surprise mass rewrite on upgrade.  ``force_storage``
        remains the tool for a deliberate, immediate sweep.

        Bytes never change: only the store key and its checksum column move, so
        ``file_size``/``index_content`` are left alone.  Each row references its
        new key before the old one becomes collectable, and the old key is only
        *marked* for GC — the sweep skips keys any other row still shares
        (dedup), so re-keying one of several rows pointing at the same file
        cannot orphan the others.

        Returns the autovacuum re-queue pair (IAVAC): a truthy *remaining*
        re-enqueues this method within the run's wall-clock budget, so a large
        backlog drains progressively instead of one batch per daily run.
        *remaining* is reported as 0 when the batch re-keyed nothing, even
        though rows still match: without that, a batch every row of which hits
        the read guard below would re-enqueue itself for the whole budget,
        re-reading the same broken rows. Those wait for the next run.

        :param limit: rows to re-key this run; defaults to the parameter
        :return: ``(re-keyed, remaining)`` — the autovacuum re-queue contract
        """
        if ALGO_TAG == "s1":
            # the fallback digest IS the legacy layout — nothing to converge to
            return 0, 0
        if limit is None:
            limit = int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("ir_attachment.rehash_legacy_keys_limit", 0)
                or 0
            )
        if limit <= 0:
            return 0, 0
        if self._storage() != "file":
            # under db/keyed storage a rewrite would MOVE content between
            # backends, which is force_storage's job, not a rehash's
            return 0, 0

        domain = Domain(
            [
                ("store_fname", "!=", False),
                # not already on the current digest...
                ("store_fname", "not =like", f"{ALGO_TAG}/%"),
                # ...and not another backend's schemed key (s3://...)
                ("store_fname", "not like", "://"),
            ]
        )
        model = self.sudo().with_context(skip_res_field_check=True)
        legacy = model.search(domain, order="id", limit=limit)
        rekeyed = 0
        backend = self._storage_backend()
        for _index, attach, raw in self._rewritable_rows(legacy, "rehash"):
            # Always re-hash: the point of this pass is to move the row onto the
            # CURRENT digest, so _migrate's reuse-the-stored-checksum shortcut
            # would defeat it (and store the content under a key that does not
            # match its own digest).
            checksum = self._content_checksum(raw)
            self._rewrite_stored_content(
                attach,
                {**backend.write(raw, checksum), "checksum": checksum},
                attach.store_fname,
            )
            rekeyed += 1
        if not rekeyed:
            # no progress: do not re-enqueue (see the docstring), retry next run
            return 0, 0
        remaining = model.search_count(domain)
        _logger.info(
            "filestore rehash: re-keyed %d attachment(s) to the %s digest "
            "(%d still on a legacy key)",
            rekeyed,
            ALGO_TAG,
            remaining,
        )
        return rekeyed, remaining

    @api.autovacuum
    def _gc_stale_filestore_temps(self) -> None:
        """Remove orphaned temp files left in the filestore ``tmp/`` directory.

        :meth:`_file_write_stream`/:meth:`_file_write` stage uploads in ``tmp/``
        before the atomic move; a worker killed mid-write leaks a temp the
        content GC never sees (it only walks the checklist). Sweep entries older
        than :attr:`_FILESTORE_TMP_MAX_AGE`, past any in-flight upload.

        Pure filesystem work (no lock); a no-op under ``db``/keyed storage via
        the early return. An actively-streamed temp keeps a recent mtime.
        """
        tmp_dir = Path(self._full_path("tmp"))
        if not tmp_dir.is_dir():
            return
        cutoff = time.time() - self._FILESTORE_TMP_MAX_AGE
        removed = 0
        for entry in tmp_dir.iterdir():
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                # a concurrent move/unlink on one entry must not abort the sweep
                _logger.info("temp gc could not remove %s", entry, exc_info=True)
        if removed:
            _logger.info("filestore temp gc: removed %d stale temp file(s)", removed)

    def _gc_checklist(
        self, limit: int | None = None, grace: float | None = None
    ) -> dict[str, Path]:
        """Return ``{fname: checklist_path}`` from the GC checklist directory.

        Pure filesystem scan (no DB), so it can run outside the table lock.

        :param limit: stop after this many entries — the sweep consuming the
            result holds a SHARE MODE lock, so this bounds the hold time
            (:attr:`_GC_MAX_ENTRIES`). ``None`` scans everything.
        :param grace: skip markers younger than this many seconds (kept for a
            later run). Defaults to :attr:`_GC_CHECKLIST_GRACE`, the age gate
            keeping the sweep off content whose INSERT may not have flushed
            (IRA-G1). Pass ``0`` to sweep regardless of age (tests).
        """
        if grace is None:
            grace = self._GC_CHECKLIST_GRACE
        cutoff = time.time() - grace
        checklist = {}
        checklist_root = Path(self._full_path("checklist"))
        skipped = 0
        capped = False
        for dirpath, _subdirs, filenames in checklist_root.walk():
            for filename in filenames:
                marker = dirpath / filename
                if grace:
                    try:
                        if marker.stat().st_mtime > cutoff:
                            skipped += 1
                            continue
                    except OSError:
                        # marker vanished mid-scan (concurrent GC) — skip it
                        skipped += 1
                        continue
                # relative_to() keeps fname correct at any nesting depth
                # (dirpath.name only works for a 2-level structure).
                fname = str(marker.relative_to(checklist_root))
                checklist[fname] = marker
                if limit is not None and len(checklist) >= limit:
                    capped = True
                    break
            if capped:
                break
        if skipped:
            _logger.debug(
                "filestore gc: %d checklist marker(s) within the grace window "
                "left for a later run",
                skipped,
            )
        return checklist

    def _gc_file_store_unsafe(
        self, checklist: dict[str, Path] | None = None, grace: float | None = None
    ) -> None:
        # The caller may pass a checklist scanned before taking the lock; tests
        # and direct callers omit it and scan here (IRA-P2-3).
        if checklist is None:
            checklist = self._gc_checklist()
        if grace is None:
            grace = self._GC_CHECKLIST_GRACE

        # Clean up the checklist in chunks, GC'ing files per chunk.
        removed = 0
        for names in batched(checklist, self.env.cr.BATCH_SIZE, strict=False):
            # determine which files to keep among the checklist
            self.env.cr.execute(
                "SELECT store_fname FROM ir_attachment WHERE store_fname = ANY(%s)",
                [list(names)],
            )
            whitelist = {row[0] for row in self.env.cr.fetchall()}

            # remove garbage files, and clean up checklist
            for fname in names:
                filepath = checklist[fname]
                if fname not in whitelist:
                    # Re-stat under the SHARE lock: a concurrent transaction may
                    # have re-marked (refreshing the mtime) and rewritten the file
                    # after _gc_checklist's pre-lock stat, its INSERT invisible to
                    # the whitelist above. Skip if now within the grace window so
                    # an in-flight write is never deleted (IRA-G1 residual race).
                    if grace:
                        try:
                            if filepath.stat().st_mtime > time.time() - grace:
                                continue
                        except OSError:
                            pass  # marker vanished — fall through to collect
                    full_path = self._full_path(fname)
                    try:
                        Path(full_path).unlink(missing_ok=True)
                        _logger.debug("_file_gc unlinked %s", full_path)
                        removed += 1
                    except OSError:
                        _logger.info(
                            "_file_gc could not unlink %s",
                            full_path,
                            exc_info=True,
                        )
                        # Keep the checklist entry so the file is retried next
                        # run instead of being permanently orphaned.
                        continue
                with contextlib.suppress(OSError):
                    Path(filepath).unlink()

        _logger.info("filestore gc %d checked, %d removed", len(checklist), removed)

    def _mark_for_gc(self, fname: str) -> None:
        """Add ``fname`` in a checklist for the filestore garbage collection."""
        self._mark_for_gc_multi((fname,))

    def _mark_for_gc_multi(self, fnames: Collection[str]) -> None:
        """Batch :meth:`_mark_for_gc`: one ``mkdir`` per shard directory.

        A bulk unlink otherwise re-creates the shard dir and probes existence
        per key (~3-4 syscalls) — felt on network filestores. ``open("ab")`` is
        idempotent, so the per-file probe is skipped. The marker mtime is the GC
        grace clock (:attr:`_GC_CHECKLIST_GRACE`); ``open("ab")`` alone doesn't
        touch it, so os.utime refreshes it — else a re-mark on content with a
        stale marker leaves it sweepable while the transaction is uncommitted.
        """
        checklist_dir = Path(self._full_path("checklist"))
        by_shard_dir: dict[Path, list[Path]] = defaultdict(list)
        for fname in fnames:
            # fname is sanitized like _full_path does (path-traversal blocked)
            full_path = checklist_dir / self._sanitize_store_path(fname)
            by_shard_dir[full_path.parent].append(full_path)
        for shard_dir, paths in by_shard_dir.items():
            with contextlib.suppress(OSError):
                shard_dir.mkdir(parents=True, exist_ok=True)
            for full_path in paths:
                with full_path.open("ab"):
                    pass
                with contextlib.suppress(OSError):
                    os.utime(full_path)

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _can_return_content(
        self, field_name: str | None = None, access_token: str | None = None
    ) -> bool:
        self.ensure_one()
        attachment_sudo = self.sudo().with_context(prefetch_fields=False)
        if access_token:
            if not consteq(attachment_sudo.access_token or "", access_token):
                msg = "Invalid access token"
                raise AccessError(msg)  # pylint: disable=missing-gettext,E8507
            return True
        if attachment_sudo.public:
            return True
        if self.env.user._is_portal():
            # Check the read access on the record linked to the attachment
            # eg: Allow to download an attachment on a task from /my/tasks/task_id
            self.check_access("read")
            return True
        return super()._can_return_content(field_name, access_token)

    def _check_access(self, operation: str) -> tuple[Self, Callable] | None:
        """Check access for attachments.

        Rules:
        - `public` is always accessible for reading.
        - If we have `res_model and res_id`, the attachment is accessible if the
          referenced model is accessible. Also, when `res_field != False` and
          the user is not an administrator, we check the access on the field.
        - If we don't have a referenced record, the attachment is accessible to
          the administrator and the creator of the attachment.
        """
        res = super()._check_access(operation)
        remaining = self
        error_func = None
        forbidden_ids = OrderedSet()
        if res:
            forbidden, error_func = res
            if forbidden == self:
                return res
            remaining -= forbidden
            forbidden_ids.update(forbidden._ids)
        elif not self:
            return None

        if operation in ("create", "unlink"):
            # check write operation instead of unlinking and creating for
            # related models and field access
            operation = "write"

        # collect the records to check (by model)
        model_ids = defaultdict(set)  # {model_name: set(ids)}
        att_model_ids = []  # [(att_id, (res_model, res_id))]
        # Memoize the field ACL per (res_model, res_field): _has_field_access is
        # deterministic per comodel/field/operation/user, so a batch backing the
        # same field evaluates it once.
        field_access: dict[tuple[str, str], bool] = {}
        # Sudo is required to access attachments across all companies.
        remaining = remaining.sudo()
        remaining.fetch(SECURITY_FIELDS)  # fetch only these fields
        for attachment in remaining:
            if attachment.public and operation == "read":
                continue
            att_id = attachment.id
            res_model, res_id = attachment.res_model, attachment.res_id
            if not self.env.is_system():
                if not res_id and attachment.create_uid.id != self.env.uid:
                    forbidden_ids.add(att_id)
                    continue
                if res_field := attachment.res_field:
                    if res_model not in self.env:
                        # model no longer exists (module uninstalled)
                        forbidden_ids.add(att_id)
                        continue
                    # Evaluate the field ACL on the comodel that declares the
                    # field: subclasses override _has_field_access (e.g. res.users
                    # self-read). Checking on self would bypass that override.
                    if (cache_key := (res_model, res_field)) not in field_access:
                        comodel = self.env[res_model]
                        field = comodel._fields.get(res_field)
                        field_access[cache_key] = field is not None and (
                            comodel._has_field_access(field, operation)
                        )
                    if not field_access[cache_key]:
                        forbidden_ids.add(att_id)
                        continue
            if res_model and res_id:
                model_ids[res_model].add(res_id)
                att_model_ids.append((att_id, (res_model, res_id)))
        forbidden_res_model_id = set(
            self._inaccessible_comodel_records(model_ids, operation)
        )
        forbidden_ids.update(
            att_id for att_id, res in att_model_ids if res in forbidden_res_model_id
        )

        if forbidden_ids:
            forbidden = self.browse(forbidden_ids)
            forbidden.invalidate_recordset(SECURITY_FIELDS)  # avoid cache pollution
            if error_func is None:

                def error_func():
                    return AccessError(
                        self.env._(
                            "Sorry, you are not allowed to access this document. "
                            "Please contact your system administrator.\n\n"
                            "(Operation: %(operation)s)\n\n"
                            "Records: %(records)s, User: %(user)s",
                            operation=operation,
                            records=forbidden[:6],
                            user=self.env.uid,
                        )
                    )

            return forbidden, error_func
        return None

    @api.constrains("res_model", "res_id")
    def _check_circular_attachment(self) -> None:
        # an attachment pointing at itself causes a recursion-depth crash when
        # its chain is walked
        for record in self.sudo():
            if record.res_model == "ir.attachment" and record.id == record.res_id:
                raise ValidationError(
                    _(
                        "You cannot attach an attachment to itself.\n"
                        "Attachment %(record)s cannot have res_id: %(res_id)s",
                        record=record.display_name,
                        res_id=record.res_id,
                    )
                )

    def _check_contents(self, values: dict[str, Any]) -> dict[str, Any]:
        mimetype = values["mimetype"] = self._mimetype_from_values(values)
        force_text = self._is_xml_like_mimetype(mimetype) and (
            self.env.context.get("attachments_mime_plainxml")
            or not self.env["ir.ui.view"].sudo(False).has_access("write")
        )
        if force_text:
            values["mimetype"] = "text/plain"
        if not self.env.context.get("image_no_postprocess"):
            values = self._postprocess_contents(values)
        return values

    def _check_serving_attachments(self) -> None:
        # Restrict writing on attachments that could be served by the
        # ir.http's dispatch exception handling.
        if self.env.is_admin():
            return
        served = self.filtered(lambda a: a.type == "binary" and a.url)
        if not served:
            return
        # group membership is per-user, hence invariant across the records
        has_group = self.env.user.has_group
        if not any(has_group(g) for g in self.get_serving_groups()):
            raise ValidationError(
                _("Sorry, you are not allowed to write on this document")
            )

    @api.model
    def _is_xml_like_mimetype(self, mimetype: str) -> bool:
        """Whether *mimetype* denotes script-bearing markup served inline.

        HTML/XHTML/HTA and the XML family (``svg+xml``, ``*+xml``) can carry
        active content a browser executes when served from the Odoo origin, so
        they are neutralized to ``text/plain`` for users not trusted to author
        views (see :meth:`_check_contents`).

        Matching is on the SUBTYPE, not a substring: the old ``"ht" in mimetype``
        false-matched unrelated types (``text/richtext``, ``x-silverlight``, ...).

        :param str mimetype: a lowercase mimetype (``maintype/subtype``)
        """
        # Office OpenXML types carry "xml" but are zip containers, not markup —
        # never neutralize (subtype matching excludes them; explicit guard).
        if mimetype.startswith("application/vnd.openxmlformats"):
            return False
        subtype = mimetype.partition("/")[2]
        return (
            "html" in subtype  # text/html, application/xhtml+xml, html-* variants
            or subtype in {"hta", "xml"}  # HTML App, text/xml, application/xml
            or subtype.endswith("+xml")  # svg+xml, mathml+xml, atom+xml, ...
        )

    def _is_remote_source(self) -> bool:
        self.ensure_one()
        return bool(
            self.url
            and not self.file_size
            and self.url.startswith(("http://", "https://", "ftp://"))
        )

    def _should_stream_upload(self, mimetype: str) -> bool:
        """Whether an upload of *mimetype* can be streamed to storage.

        Streaming bypasses the in-memory content pipeline, so it is used only
        when no transform rewrites the bytes. The one such transform is image
        autoresize, so buffer only an image that autoresize may shrink and
        stream everything else.
        """
        if self.env.context.get("image_no_postprocess"):
            return True
        maintype, _, subtype = (mimetype or "").partition("/")
        if maintype != "image":
            return True
        subtypes, max_width, _height, _quality = self._get_image_autoresize_config()
        return not (max_width and subtype in subtypes)
