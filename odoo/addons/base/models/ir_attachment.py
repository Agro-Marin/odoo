import base64
import contextlib
import functools
import hashlib
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
    human_size,
    image,
    str2bool,
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
    """Resolve the filestore root once per path string.

    The root is constant per database for the process lifetime, but
    ``_full_path`` runs on every filestore read/write/GC entry and
    ``Path.resolve()`` costs a per-component syscall walk (felt on
    network-mounted filestores). Re-pointing the root symlink mid-run is
    not supported — a restart is required, as for any filestore move.
    """
    return Path(filestore).resolve()


def condition_values(
    model: Any, field_name: str, domain: Domain
) -> Collection[Any] | None:
    """Extract the restricted values for *field_name* from *domain*.

    :return: the values of an ``=`` or ``in`` condition on *field_name*
        (a materialized collection), or ``None`` when the domain does not
        restrict the field with those operators. ``None`` is also returned
        when the condition's value is a lazy object (``Query``/``SQL``/
        ``Domain``, all legal ``in`` values): callers probe the result with
        ``in`` / ``len()``, which on a ``Query`` would silently execute and
        scan the subquery. Treating it as "unrestricted" is the safe
        over-approximation — both callers then take their general path.
    """
    domain = domain.optimize(model)
    # Keep only '='/'in' conditions on *field_name*, dropping everything else to
    # TRUE, then re-optimize. optimize() merges same-field conditions, so the
    # result holds AT MOST ONE condition on the field — there is nothing to
    # iterate, only a single condition to read (or none). A field constrained
    # through an OR with another field collapses away here and yields None,
    # which callers treat as "unrestricted" (the safe over-approximation).
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
    """Attachments are used to link binary files or url to any Odoo document.

    External attachment storage
    ---------------------------

    Content storage is pluggable: subclass
    :class:`~odoo.addons.base.models.ir_attachment_storage.AttachmentStorage`
    and register it with ``@register_storage``. Two dispatch axes:

    * **write side** — the ``ir_attachment.location`` parameter decides where
      NEW content goes (:meth:`_storage_backend`);
    * **read side** — existing content follows the record's store key,
      resolved by URI scheme (``s3://...``) via :meth:`_backend_for_key`,
      so rows written before a location switch keep working. Plain sharded
      keys (``ab/<sha1>``) belong to the local filestore.

    ``migration_domain`` (used by :meth:`force_storage`) is backend-defined:
    a custom backend must match every row it does NOT own (db rows and
    other backends' keys) to claim them; the file backend keeps its
    historical ``db_datas`` domain, so file→custom migration is driven by
    the custom backend's own domain, not the file backend's.

    The ``_file_*`` methods are the LOCAL FILESTORE primitives (the file
    backend delegates to them); override them only to change how the local
    store itself works. Partial-read callers stay backend-agnostic via
    ``_backend_for_key(key).read(key, size)`` (e.g. ``documents/tools.py``).

    The default backend stores files on the local filesystem, named and
    deduplicated by the SHA-1 hash of their content.

    Review tags
    -----------

    Comments carry ``IRA-*`` tags (e.g. ``IRA-B5``, ``IRA-P1-3``) that
    cross-reference a hard-won invariant to the test that pins it: grep a tag
    across this module and ``base/tests/test_ira*`` / ``test_ir_attachment``
    to find both the rationale and its regression test. A tag with no matching
    test marks an invariant whose guard is still implicit — a standing
    invitation to add one.
    """

    _name = "ir.attachment"
    _description = "Attachment"
    _order = "id desc"

    name = fields.Char("Name", required=True)
    description = fields.Text("Description")
    res_name = fields.Char("Resource Name", compute="_compute_res_name")
    res_model = fields.Char("Resource Model")
    res_field = fields.Char("Resource Field")
    res_id = fields.Many2oneReference("Resource ID", model_field="res_model")
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

    # for external access
    access_token = fields.Char("Access Token", groups="base.group_user")

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
    # Direct db_datas create/write bypasses the content pipeline on purpose
    # (no checksum/file_size/index recompute, no storage dispatch); use
    # 'raw'/'datas' for normal content. test_http's static-serve tests rely
    # on this raw-column escape hatch (missing-checksum serving path).
    db_datas = fields.Binary("Database Data", attachment=False)
    store_fname = fields.Char("Stored Filename", index=True)
    file_size = fields.Integer("File Size", readonly=True)
    checksum = fields.Char("Checksum/SHA1", size=40, readonly=True)
    mimetype = fields.Char("Mime Type", readonly=True)
    index_content = fields.Text("Indexed Content", readonly=True, prefetch=False)

    _res_field_idx = models.Index("(res_model, res_field, res_id)")
    _checksum_idx = models.Index("(checksum) WHERE checksum IS NOT NULL")

    # Maximum number of res_model values for which _search builds a
    # per-model security domain (one comodel subquery each); above this,
    # the batched fetch-and-filter fallback is used instead.
    _SEARCH_MODEL_DOMAIN_LIMIT = 5

    # Size of the lowest-id window that _audit_url_attachments materializes and
    # tracks per run. The logged total still reflects the true magnitude of a
    # burst regardless of this cap; the cap only bounds what is held in memory
    # and persisted in `ir_attachment.url_audit_seen`. Override per subclass.
    _URL_AUDIT_WINDOW = 20

    # Cap the bytes scanned and stored by _index. A large text upload would
    # otherwise spill an unbounded index_content into the DB (and spike memory
    # building the full match list); full-text search only needs a prefix.
    # Override per subclass to index more/less.
    _INDEX_MAX_BYTES = 4 * 1024 * 1024

    # Chunk size for streaming uploads into the filestore: peak memory per
    # upload is O(this), not O(file size). Override per subclass to tune.
    _STREAM_CHUNK_SIZE = 128 * 1024

    # Age (seconds) above which a leftover file in the filestore ``tmp/`` dir is
    # considered orphaned and swept by the GC. Streaming uploads write there for
    # the whole upload duration before the atomic move; a worker killed mid-
    # upload leaves the temp behind, unreachable by the content GC (which only
    # walks the checklist). The threshold must comfortably exceed the longest
    # legitimate upload so an in-flight temp is never collected. See _file_write_stream.
    _FILESTORE_TMP_MAX_AGE = 24 * 3600

    # Cap the number of checklist entries a single filestore-GC run processes:
    # the sweep holds a SHARE MODE lock on ir_attachment for its whole
    # duration, during which every attachment write blocks — after a bulk
    # delete the checklist can hold hundreds of thousands of entries. Entries
    # past the cap stay on disk and are swept by the next (nightly) run.
    # Override per subclass to tune. See FileStorage.autovacuum.
    _GC_MAX_ENTRIES = 100_000

    # Minimum age (seconds) of a checklist marker before the filestore GC may
    # sweep it (IRA-G1). The content pipeline writes the file and marks it for
    # GC BEFORE the row's INSERT is flushed (create()'s write-as-we-go path;
    # _set_attachment_data persists before flush_recordset), so until the
    # INSERT executes the creating transaction holds no lock on ir_attachment:
    # a concurrent GC's SHARE MODE lock is granted, the whitelist query cannot
    # see the uncommitted row, and the freshly written content is deleted out
    # from under a transaction that will commit a store_fname pointing at
    # nothing. The marker mtime is the grace clock — refreshed on every
    # (re-)mark, including dedup hits (see _mark_for_gc_multi) — and, like
    # _FILESTORE_TMP_MAX_AGE above, the threshold must comfortably exceed the
    # longest legitimate transaction that writes attachment content (bulk
    # imports, migrations). Sweep latency only grows by up to one nightly GC
    # cycle. Override per subclass to tune.
    _GC_CHECKLIST_GRACE = 24 * 3600

    def _check_res_field_access(self, res_model: str, res_field: str) -> None:
        """Validate write access to a field-backing attachment's target field.

        The plain ``res_field`` Char has no ``groups``, so mutating it would
        otherwise bypass the field-group ACL enforced on read by
        ``_check_access``. Mirror that check at create/write time. See IRA-L2.

        :param str res_model: the comodel name the attachment is linked to
        :param str res_field: the comodel field name the attachment backs
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
        """Decode a base64 ``datas`` payload, raising a clean error if invalid.

        The single decode wrapper for every content entry point accepting
        ``datas`` (:meth:`_normalize_content_vals`, :meth:`_mimetype_from_values`,
        :meth:`create_unique`). ``b64decode`` raises ``binascii.Error`` (a
        ``ValueError`` subclass) on malformed padding/length and a plain
        ``ValueError`` on non-ASCII input; surface either as a
        :class:`UserError` instead of a 500.

        :param datas: the base64 payload (bytes/str), falsy decodes to ``b""``
        :raise UserError: if *datas* is not valid base64
        :rtype: bytes
        """
        try:
            return base64.b64decode(datas or b"")
        except ValueError as exc:
            raise UserError(_("Attachment is not encoded in base64.")) from exc

    def _normalize_content_vals(self, vals: dict[str, Any]) -> bool:
        """Collapse the content keys of create/write *vals* into a single ``raw``.

        Single source of truth for content normalization, shared by
        :meth:`create` and :meth:`write` so the two cannot drift apart.
        Mutates *vals* in place:

        * ``raw`` wins over ``datas`` by KEY PRESENCE, not truthiness — an
          explicit empty ``raw`` beats a ``datas`` payload (IRA-A3);
        * ``str`` content is encoded to ``bytes``; an absent-but-present or
          empty value normalizes to ``b""``;
        * the computed metadata columns (``file_size``/``checksum``/
          ``store_fname``/``index_content``) are stripped — they are derived
          from the content and must never be set through the public create/write
          API. ``index_content`` was previously omitted, so a writer with access
          could inject arbitrary full-text index text via
          ``write({'index_content': ...})`` while its peer derived columns were
          protected (IRA-C3).

        Vals carrying NEITHER ``raw`` NOR ``datas`` are left untouched (url
        rows, direct ``db_datas`` passthrough): the caller must not treat them
        as empty content (IRA-R1).

        :param dict vals: create or write values, mutated in place
        :return: whether *vals* carried a content key (``raw`` or ``datas``)
        :rtype: bool
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

    # Content-metadata derivation runs in TWO places BY DESIGN — do not unify:
    # create() computes file_size/checksum/index_content/store_fname INLINE and
    # pops 'raw' (so the inverse does not re-run), which enables the
    # write-as-we-go filestore write that keeps a batch create flat in memory;
    # write() instead leaves 'raw' in vals and lets _inverse_raw ->
    # _set_attachment_data derive them. Both paths converge on the shared
    # _normalize_content_vals + _get_datas_related_values helpers, which is what
    # keeps them from drifting. Collapsing them onto one mechanism reintroduces
    # the O(total bytes) buffering this split exists to avoid.
    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        # Copy first: _normalize_content_vals rewrites/strips keys in place and
        # the caller's dicts must not be mutated (model_create_multi contract).
        vals_list = [dict(vals) for vals in vals_list]

        # Fail-fast on the ir.attachment-level create ACL, mirroring write()'s
        # leading check_access("write"). super().create() re-checks, but only
        # AFTER SHA-1 hashing, _index and the filestore write have already run
        # for a user who cannot create here. No-op under su (the content hot
        # path). Check on an EMPTY recordset (self.browse()): create() may be
        # invoked on a populated recordset (e.g. via copy()), and a non-empty
        # check_access would wrongly evaluate record-level ir.rule for 'create'
        # against those EXISTING rows. _check_access documents this exact
        # empty-recordset model-ACL pattern ("at the start of create()").
        self.browse().check_access("create")

        # Fail-fast: run the comodel/field access checks on cheap metadata
        # BEFORE any content post-processing. write() documents the same
        # principle ("avoids running content post-processing for a user who
        # cannot write these rows"); create() must match it, otherwise an
        # unauthorized create still pays for SHA-1 hashing, _index scanning and
        # image autoresize it will only reject. res_model/res_id/res_field are
        # untouched by the content pipeline, so reading them here is safe.
        model_and_ids = defaultdict(OrderedSet)  # {res_model: {res_id}}
        for values in vals_list:
            # a new res_field must pass the comodel field's ACL (IRA-L2)
            if res_field := values.get("res_field"):
                self._check_res_field_access(values.get("res_model"), res_field)
            # 'check()' only uses res_model and res_id from values. Group by
            # model so the comodel access check issues one query per model even
            # when creating multiple attachments on a single record.
            # (don't use a possible contextual recordset for check, see commit)
            model_and_ids[values.get("res_model")].add(values.get("res_id"))
        if any(self._inaccessible_comodel_records(model_and_ids, "write")):
            raise AccessError(_("Sorry, you are not allowed to access this document."))

        # Access granted: run the (potentially expensive) content pipeline.
        # Resolve the write-side backend once for the whole batch: it feeds
        # _get_datas_related_values (which both persists the payload and returns
        # its store fragment), instead of being rebuilt per attachment.
        backend = self._storage_backend()
        # {(checksum, mimetype): datas-related values} — a batch repeating the
        # same payload (mail templates, imports) otherwise re-runs _index, the
        # SHA-1 pass and the filestore write once per row over identical bytes.
        # The memo both dedups the metadata derivation AND, since
        # _get_datas_related_values persists the content, writes each distinct
        # payload exactly once. Keyed on the content checksum, NOT id(raw): the
        # base64-'datas' path decodes a DISTINCT object per row (no identity
        # hits), and holding payload references to make id() sound would retain
        # O(total bytes); the derived dicts hold no payload on the file backend
        # (on the db backend the payload is carried by vals_list anyway). The
        # content is written before super().create() runs, which is safe:
        # content-addressed, so a rollback leaves the file orphaned but marked
        # for GC — exactly the state the post-super() write already produced
        # when _check_serving_attachments rejected the batch.
        derived_values: dict[tuple[str, str], dict[str, Any]] = {}
        for values in vals_list:
            # Shared raw/datas precedence + metadata stripping (IRA-A3).
            has_content = self._normalize_content_vals(values)

            # _check_contents mutates `values` in place and returns it; even if
            # an override forks a new dict here, create() stays correct because
            # _inverse_raw re-derives content metadata post-create (see
            # test_a1_create_is_robust_to_new_dict_override).
            values = self._check_contents(values)
            if has_content:
                # pop() must always run on this branch so _inverse_raw does not
                # re-process the content after create.
                raw = values.pop("raw")
                # Compute checksum/file_size/db_datas even for explicitly empty
                # content, so an emptied attachment is identical whether created
                # or written (IRA-P0-7). Vals with NO content key (url rows,
                # direct 'db_datas' passthrough) are left untouched: defaulting
                # raw to b"" here overwrote a caller's db_datas with empty bytes
                # and stamped sha1(b"") on content-less rows (IRA-R1, pinned by
                # test_http test_static17/18).
                memo_key = (self._content_checksum(raw), values["mimetype"])
                if memo_key not in derived_values:
                    # Persists the payload (once per distinct memo_key) and
                    # returns the store fragment; `raw` is rebound each
                    # iteration so the decoded payload is released instead of
                    # accumulating into O(total bytes).
                    derived_values[memo_key] = self._get_datas_related_values(
                        raw, values["mimetype"], backend, checksum=memo_key[0]
                    )
                values.update(derived_values[memo_key])

        records = super().create(vals_list)
        records._check_serving_attachments()
        return records

    def write(self, vals: dict[str, Any]) -> bool:
        # Deliberate fail-fast: super().write() re-checks, but checking here
        # avoids running content post-processing for a user who cannot write
        # these rows. Both checks are skipped under sudo (the content hot
        # path), so the redundant pair only affects non-su metadata writes.
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
                # One check per distinct comodel, not per record: the field ACL
                # is deterministic per (res_model, res_field, operation, user),
                # the same reason _check_access memoizes its field_access map.
                for res_model in OrderedSet(record.res_model for record in self):
                    self._check_res_field_access(res_model, res_field)
        # Normalize content keys exactly like create() via the shared helper:
        # 'raw' beats 'datas' by key presence, str content is encoded, and the
        # computed metadata columns are stripped. Without this the two inverses
        # would run in vals key order and the *last* key would silently win —
        # the opposite of create() — and the base64 payload would be decoded
        # several times along the write path.
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
            # No explicit content override — preserve the original content.
            # db-stored content is carried through `raw` so checksum and
            # friends are recomputed from it; filestore-backed attachments
            # are instead relinked to their existing content-addressed file
            # in copy(), without reading the bytes (see IRA-B4: reading them
            # only made _file_write dedup back to the same file, and a
            # transient read failure silently produced an empty copy).
            for attachment, vals in zip(self, vals_list, strict=True):
                # Carry content only when the original actually HAS content:
                # checksum is stamped for pipeline content (including an
                # explicitly-empty binary), db_datas for the raw escape hatch.
                # A content-less row (type='url', or empty with no metadata) has
                # neither — carrying raw=b"" there stamped sha1(b"")/file_size=0
                # onto the copy that the original never had (IRA-C4).
                if not attachment.store_fname and (
                    attachment.checksum or attachment.db_datas
                ):
                    vals["raw"] = attachment.raw
        return vals_list

    def copy(self, default: ValuesType | None = None) -> Self:
        new_attachments = super().copy(default)
        if not (default or {}).keys() & {"datas", "db_datas", "raw"}:
            # Relink filestore-backed copies to the original file: same
            # checksum, same store path, zero bytes read (see copy_data).
            # create() stripped the content metadata, so the rows were
            # created empty; restore it from the originals. The direct
            # super().write call mirrors _set_attachment_data: content
            # metadata is internal and must bypass subclass write overrides.
            # strict zip: copy_data may drop duplicate-id entries, in which
            # case positional relinking is impossible — fail loudly rather
            # than leave silently empty copies (the previous code raised
            # TypeError on that same input).
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
        # First delete in the database, *then* in the filesystem if the
        # database allowed it. Helps avoid errors when concurrent transactions
        # are deleting the same file, and some of the transactions are
        # rolled back by PostgreSQL (due to concurrent updates detection).
        # (The asset-bundle ormcache invalidation lives in the ir.attachment
        # ESM extension's unlink override, see ir_attachment_assets.py.)
        to_delete = OrderedSet(
            attach.store_fname for attach in self if attach.store_fname
        )
        res = super().unlink()
        # key-axis dispatch: the content follows its store key, not the
        # currently configured location. Batched: plain filestore keys are
        # GC-marked in one grouped pass (one mkdir per shard directory).
        self._storage_delete_multi(to_delete)
        return res

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
            # Drop ids that no longer exist: a dangling res_id otherwise raises
            # MissingError reading display_name and breaks the whole list view.
            # Likewise drop records the user cannot read (e.g. a public
            # attachment linked to a restricted record): display_name would
            # raise AccessError. Both degrade to res_name = False.
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
            if attach.store_fname:
                # key-axis dispatch: content follows its store key, not the
                # configured location (plain keys → local filestore)
                data = attach._backend_for_key(attach.store_fname).read(
                    attach.store_fname
                )
                if not data:
                    # A store key is only ever set for NON-empty content (empty
                    # content stays inline as db_datas), so an empty read means
                    # the referenced file is missing or unreadable — not
                    # legitimately empty. The backend swallows the I/O error and
                    # returns b""; surface it here with the record identity so a
                    # transient/permanent filestore fault is observable instead
                    # of silently serving empty bytes to readers (reports, mail,
                    # exports). The _migrate data-loss guard keys off the same
                    # empty-read-on-non-empty-row signal.
                    _logger.error(
                        "Unreadable filestore content for attachment %s "
                        "(store_fname=%s); serving empty bytes",
                        attach.id,
                        attach.store_fname,
                    )
                attach.raw = data
            else:
                attach.raw = attach.db_datas

    def _content_checksum(self, bin_data: bytes) -> str:
        """Return the SHA-1 hex digest of *bin_data* (for content-addressed storage)."""
        # an empty file has a checksum too (for caching)
        return hashlib.sha1(bin_data or b"", usedforsecurity=False).hexdigest()

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
                # Unreachable via create/write, which decode 'datas' upstream,
                # but direct callers of this hook get the same clean UserError.
                raw = self._decode_datas(values["datas"])
            if raw:
                mimetype = guess_mimetype(raw)
        return (mimetype and mimetype.lower()) or "application/octet-stream"

    def _inverse_raw(self) -> None:
        self._set_attachment_data(lambda a: a.raw or b"")

    def _inverse_datas(self) -> None:
        self._set_attachment_data(lambda attach: base64.b64decode(attach.datas or b""))

    @api.model
    def _storage(self) -> str:
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("ir_attachment.location", "file")
        )

    @api.model
    def _filestore(self) -> str:
        return config.filestore(self.env.cr.dbname)

    @api.model
    def _storage_backend(self) -> AttachmentStorage:
        """Return the write-side backend for the configured storage location.

        Write-side only: it decides where NEW content goes. Existing content
        follows the record's store key (see :meth:`_backend_for_key`) — the
        two can differ, since changing ``ir_attachment.location`` does not
        migrate rows. Unknown locations fall back to :class:`FileStorage`
        (they behave file-like everywhere else).
        """
        backend_cls = STORAGE_BACKENDS.get(self._storage(), FileStorage)
        return backend_cls(self.env)

    @api.model
    def _backend_for_key(self, fname: str) -> AttachmentStorage:
        """Return the read-side backend owning the store key *fname*.

        Dispatch is by URI scheme (``s3://...``); plain sharded fnames
        belong to the local filestore.
        """
        return backend_for_key(self.env, fname)

    @api.model
    def _get_storage_domain(self) -> list[tuple[str, str, Any]]:
        """Return the domain matching attachments NOT in the current storage."""
        return self._storage_backend().migration_domain()

    def _get_pdf_raw(self) -> bytes | None:
        """Return raw PDF bytes if this attachment is a binary PDF, else None."""
        self.ensure_one()
        if self.type != "binary" or not (self.mimetype or "").startswith(
            "application/pdf"
        ):
            return None
        return self.raw or None

    @api.model
    def force_storage(self) -> None:
        """Force all attachments to be stored in the currently configured storage"""
        if not self.env.is_admin():
            raise AccessError(_("Only administrators can execute this action."))

        # Migrate only binary attachments, including those linked to binary
        # fields (which are normally hidden by the _search override).
        self.with_context(skip_res_field_check=True).search(
            Domain.AND([self._get_storage_domain(), [("type", "=", "binary")]])
        )._migrate()

    def _migrate(self) -> None:
        record_count = len(self)
        backend = self._storage_backend()
        storage = self._storage().upper()
        _logger.info("Migrating %d attachments to %s", record_count, storage)
        # Make progress durable batch-by-batch on live runs: a filestore-wide
        # force_storage otherwise holds one giant transaction (row locks, WAL
        # bloat, full restart on crash). Re-runs are idempotent: force_storage
        # re-searches the migration domain, which no longer matches migrated
        # rows. Tests run inside a savepoint, where commit is forbidden.
        can_commit = not (modules.module.current_test or config["test_enable"])
        for index, attach in enumerate(self, 1):
            if index % 100 == 0 or index == record_count:
                _logger.info(
                    "Migrating attachment %d/%d to %s", index, record_count, storage
                )
            raw = attach.raw
            # Data-loss guard: _file_read returns b"" on a (possibly transient)
            # read error. Writing that back would blank the record and mark the
            # only copy of the content for GC. Never overwrite a non-empty file
            # with an empty read — skip and let a later run retry.
            if not raw and attach.file_size:
                _logger.error(
                    "Skipping migration of attachment %s: read returned empty "
                    "for a non-empty file (file_size=%s, store_fname=%s)",
                    attach.id,
                    attach.file_size,
                    attach.store_fname,
                )
                continue
            # A storage-LOCATION migration does not change the bytes, so reuse
            # the already-derived checksum/file_size/index_content and move only
            # the store-location fragment (store_fname/db_datas). This skips the
            # full SHA-1 re-hash and re-index that the content-write path runs on
            # every row, recomputing provably identical values (P1). Bypassing
            # that path also removes the autoresize risk the old
            # image_no_postprocess context had to guard against. Rows written
            # through the raw db_datas escape hatch never had this metadata
            # stamped (no checksum, stale file_size), so fall back to a full
            # derivation for them.
            reuse = bool(attach.checksum) and attach.file_size == len(raw)
            checksum = attach.checksum if reuse else self._content_checksum(raw)
            old_fname = attach.store_fname
            # Both branches persist the content into the target backend and
            # return its store fragment in one step (the store key is the
            # write's own return value). The reuse fast path moves ONLY the
            # store-location fragment, keeping the already-derived
            # checksum/file_size/index_content untouched; the full path
            # re-derives them. The new content is written before the flush
            # below, so the row never references a not-yet-written file.
            super(IrAttachment, attach.sudo()).write(
                backend.write(raw, checksum)
                if reuse
                else self._get_datas_related_values(raw, attach.mimetype, backend)
            )
            # Reference the new location before the old key becomes collectable.
            attach.flush_recordset(
                ["store_fname", "db_datas", "checksum", "file_size", "index_content"]
            )
            if old_fname:
                # key-axis dispatch: the old content may live in a backend other
                # than the target one (location switches don't migrate rows).
                attach._storage_delete(old_fname)
            # Drop the just-written binary from cache so memory stays flat over a
            # filestore-wide migration instead of growing O(total bytes) (P2-6).
            attach.invalidate_recordset()
            if can_commit and index % 100 == 0:
                self.env.cr.commit()

    @api.model
    def _sanitize_store_path(self, path: str) -> str:
        """Neutralize traversal vectors in a store path (dots, colons, leading/trailing separators)."""
        return re.sub(r"[.:]", "", path).strip("/\\")

    @api.model
    def _full_path(self, path: str) -> str:
        path = self._sanitize_store_path(path)
        filestore = _resolve_filestore_root(self._filestore())
        full = (filestore / path).resolve()
        # Ensure the resolved path is within the filestore (defense-in-depth).
        # Use is_relative_to() for proper path-component checking — str.startswith()
        # would incorrectly accept sibling dirs like /data/odoo-evil for /data/odoo.
        if not full.is_relative_to(filestore):
            raise ValueError(f"Attachment path {path!r} escapes the filestore")
        return str(full)

    @api.model
    def _file_store_path(self, checksum: str) -> str:
        """Return the content-addressed *relative* store path for *checksum*.

        This is the value kept in ``store_fname``. Files are scattered across
        256 shard directories by the first two hex chars of the SHA-1; the
        actual filesystem work lives in :meth:`_get_path` / :meth:`_file_write`.

        :param str checksum: the SHA-1 hex digest of the content
        :rtype: str
        """
        # we use '/' in the db (even on windows)
        return checksum[:2] + "/" + checksum

    @api.model
    def _get_path(self, bin_data: bytes, sha: str) -> tuple[str, str]:
        """Return ``(fname, full_path)`` for storing *bin_data* in the filestore.

        Files are scattered across 256 directories using the first two hex
        characters of the SHA-1 hash.  The directory is created if needed,
        and a SHA-1 collision check is performed.
        """
        fname = self._file_store_path(sha)
        full_path = Path(self._full_path(fname))
        full_path.parent.mkdir(exist_ok=True, parents=True)

        # prevent sha-1 collision: on a dedup hit the whole stored file is read
        # back to rule out a collision serving the wrong bytes. That full read
        # dominates large-file dedup, so it is opt-out (_verify_content_collision).
        if (
            full_path.is_file()
            and self._verify_content_collision()
            and not self._same_content(bin_data, str(full_path))
        ):
            raise UserError(_("The attachment collides with an existing file."))
        return fname, str(full_path)

    @api.model
    def _file_read(self, fname: str, size: int | None = None) -> bytes:
        full_path = self._full_path(fname)
        try:
            with Path(full_path).open("rb") as f:
                return f.read(size)
        except OSError:
            _logger.info("_file_read reading %s", full_path, exc_info=True)
        return b""

    @api.model
    def _file_write(self, bin_value: bytes, checksum: str) -> str:
        fname, full_path = self._get_path(bin_value, checksum)
        if Path(full_path).exists():
            # Dedup hit: (re-)mark so the marker's mtime — the GC grace
            # clock — covers THIS transaction's create window too. The
            # existing file may be an orphan of an aborted transaction
            # whose marker predates the grace window; without the refresh
            # the GC could sweep it before this transaction's INSERT is
            # flushed. Aligned with _file_write_stream, which always
            # marked on dedup hits (IRA-G1).
            self._mark_for_gc(fname)
        else:
            # Stage in the filestore tmp/ dir, then atomically replace into the
            # content-addressed path. A crash thus never leaves a truncated file
            # at that path — which would otherwise fail every future
            # _same_content check with a spurious collision UserError and block
            # re-uploads of that content permanently. Staging in tmp/ — rather
            # than the shard dir, as before — means a crash BEFORE the replace
            # leaves the orphan where _gc_stale_filestore_temps can sweep it; a
            # shard-dir temp was reachable by no GC (neither the checklist walk
            # nor the tmp/ sweep) and leaked forever. tmp/ shares the filestore
            # root with the shard dirs, so replace() stays atomic (same
            # filesystem, no cross-fs copy), exactly as _file_write_stream does.
            tmp_dir = Path(self._full_path("tmp"))
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = tmp_dir / f"write-{uuid.uuid4().hex}"
            try:
                with tmp_path.open("wb") as fp:
                    fp.write(bin_value)
                tmp_path.replace(full_path)
                # add fname to checklist, in case the transaction aborts
                self._mark_for_gc(fname)
            except OSError:
                _logger.info("_file_write writing %s", full_path, exc_info=True)
                with contextlib.suppress(OSError):
                    tmp_path.unlink()
                raise
        return fname

    @api.model
    def _file_write_stream(
        self, fileobj: Any, *, chunk_size: int | None = None
    ) -> tuple[str, int, str]:
        """Stream *fileobj* into the filestore, hashing as it goes.

        Reads *fileobj* in chunks, writing each to a temp file while updating a
        running SHA-1, then atomically moves the temp into its
        content-addressed path (or drops it on a dedup hit). Peak memory is one
        chunk, never the whole payload — the streaming counterpart of
        :meth:`_file_write`, which requires the full ``bytes`` up front.

        :param fileobj: a binary file-like supporting ``read(size)``
        :return: ``(store_fname, file_size, checksum)``; ``store_fname`` is
            ``""`` for empty content (the caller keeps it inline as db_datas)
        :rtype: tuple
        """
        chunk_size = chunk_size or self._STREAM_CHUNK_SIZE
        digest = hashlib.sha1(usedforsecurity=False)
        size = 0
        tmp_dir = Path(self._full_path("tmp"))
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"stream-{uuid.uuid4().hex}"
        try:
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
            fname = self._file_store_path(checksum)
            full_path = Path(self._full_path(fname))
            full_path.parent.mkdir(exist_ok=True, parents=True)
            if full_path.is_file():
                # dedup hit: rule out a SHA-1 collision file-vs-file (no
                # buffering) before discarding the just-streamed temp. Opt-out
                # via the same param as _get_path.
                if self._verify_content_collision() and not self._same_content_files(
                    str(tmp_path), str(full_path)
                ):
                    tmp_path.unlink(missing_ok=True)
                    raise UserError(_("The attachment collides with an existing file."))
                tmp_path.unlink(missing_ok=True)
            else:
                # atomic within the filestore (same filesystem), like _file_write
                tmp_path.replace(full_path)
            # add fname to checklist, in case the transaction aborts
            self._mark_for_gc(fname)
            return fname, size, checksum
        except OSError:
            _logger.info("_file_write_stream writing %s", tmp_path, exc_info=True)
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise

    @api.model
    def _same_content_files(self, path_a: str, path_b: str) -> bool:
        """Return whether two files hold identical bytes (streamed compare).

        File-vs-file counterpart of :meth:`_same_content`, used by
        :meth:`_file_write_stream` so a dedup collision check never buffers
        either side.
        """
        if Path(path_a).stat().st_size != Path(path_b).stat().st_size:
            return False
        BLOCK_SIZE = 65536
        with Path(path_a).open("rb") as fa, Path(path_b).open("rb") as fb:
            while True:
                chunk_a = fa.read(BLOCK_SIZE)
                if chunk_a != fb.read(BLOCK_SIZE):
                    return False
                if not chunk_a:
                    return True

    @api.model
    def _file_delete(self, fname: str) -> None:
        # simply add fname to checklist, it will be garbage-collected later
        self._mark_for_gc(fname)

    @api.model
    def _storage_delete(self, fname: str) -> None:
        """Schedule deletion of the content at *fname* in its owning backend.

        Key-axis dispatch (:meth:`_backend_for_key`): the key may live in a
        backend other than the currently configured one, since changing
        ``ir_attachment.location`` does not migrate existing rows.
        """
        self._backend_for_key(fname).delete(fname)

    @api.model
    def _storage_delete_multi(self, fnames: Collection[str]) -> None:
        """Batch counterpart of :meth:`_storage_delete`.

        Scheme-keyed content (``s3://...``) still dispatches per key to its
        owning backend; plain filestore keys — the overwhelmingly common
        case — are checklist-marked in one grouped pass
        (:meth:`_mark_for_gc_multi`) instead of paying the per-key
        ``FileStorage.delete`` → :meth:`_file_delete` indirection and its
        3-4 syscalls per key. A deployment that overrides the local-store
        delete primitive (:meth:`_file_delete`) to change deletion semantics
        must override this method too.
        """
        plain_fnames = []
        for fname in fnames:
            if "://" in fname:
                self._backend_for_key(fname).delete(fname)
            else:
                plain_fnames.append(fname)
        if plain_fnames:
            self._mark_for_gc_multi(plain_fnames)

    def _mark_for_gc(self, fname: str) -> None:
        """Add ``fname`` in a checklist for the filestore garbage collection."""
        self._mark_for_gc_multi((fname,))

    def _mark_for_gc_multi(self, fnames: Collection[str]) -> None:
        """Batch :meth:`_mark_for_gc`: one ``mkdir`` per shard directory.

        A bulk unlink otherwise re-creates the same shard directory and
        re-probes existence once per key (~3-4 syscalls each) — felt on
        network filestores. The per-file ``exists()`` probe is skipped
        entirely: ``open("ab")`` is idempotent (it creates the empty marker
        or touches nothing that matters on an existing one).

        The marker's mtime is the GC grace clock (see
        :attr:`_GC_CHECKLIST_GRACE`), so a RE-mark must refresh it —
        ``open("ab")`` alone does not touch the mtime of an existing
        marker. Without the refresh, a transaction dedup-hitting content
        whose stale marker predates the grace window would leave that
        content sweepable while the transaction is still uncommitted.
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

    @api.model
    def _same_content(self, bin_data: bytes, filepath: str) -> bool:
        """Return whether *filepath* holds exactly *bin_data*.

        :param bytes bin_data: the candidate content
        :param str filepath: path to the existing file (caller guarantees it exists)
        :rtype: bool
        """
        # Fast reject: same content implies same size, and stat() is far cheaper
        # than reading the whole file (the common case is a SHA-1 collision check
        # on a large duplicate upload).
        if Path(filepath).stat().st_size != len(bin_data):
            return False
        BLOCK_SIZE = 65536
        view = memoryview(bin_data)  # slice without copying
        with Path(filepath).open("rb") as fd:
            offset = 0
            while chunk := fd.read(BLOCK_SIZE):
                if chunk != view[offset : offset + len(chunk)]:
                    return False
                offset += len(chunk)
        return True

    @api.model
    def _verify_content_collision(self) -> bool:
        """Whether to byte-compare the stored file against new content on dedup.

        The filestore is content-addressed by SHA-1. On a dedup hit (the target
        file already exists), :meth:`_get_path` re-reads the whole stored file
        to rule out a SHA-1 collision serving the wrong bytes — a cost paid on
        every duplicate upload that dominates large-file dedup. The content
        hash is already declared ``usedforsecurity=False``, so operators that
        accept the content-addressing trust model can disable the re-read via
        the ``ir_attachment.verify_content_collision`` parameter.

        :return: ``True`` (verify, the safe default) unless explicitly disabled
        :rtype: bool
        """
        return str2bool(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("ir_attachment.verify_content_collision", "True"),
            True,
        )

    @api.autovacuum
    def _audit_url_attachments(self) -> None:
        """Defense-in-depth observation for ``ir.http._serve_fallback``.

        That fallback serves any ``type='binary'`` attachment whose ``url``
        matches the request path under ``sudo()``. Any attachment with
        ``url`` set AND ``public=False`` is an oddity worth reviewing:
        the usual pattern for a served attachment is ``public=True``
        (web assets, sitemaps). A non-public record serving a URL
        suggests either a configuration error or a future controller
        leaking user input into ``vals``.

        ``_check_serving_attachments`` already blocks non-admin writes
        with ``url`` set — this vacuum catches what slips through
        ``sudo()`` bypasses. Intentionally an observation, not a hard
        block: the fix for a real hit is to either strip ``url`` from
        the offending controller or tighten ``_get_serve_attachment``
        to require ``public=True``.

        Each offending row is reported at WARNING once (when first seen),
        then at INFO while it remains unresolved — re-warning nightly for
        the same acknowledged rows only trains operators to ignore the
        audit. Seen ids persist in ``ir_attachment.url_audit_seen``; a row
        that is fixed and later re-broken is warned again.

        Only the lowest-id window (:attr:`_URL_AUDIT_WINDOW`) is materialized
        and tracked, so a NEW high-id offender is surfaced individually only
        once the lower-id ones are resolved and leave the window. The logged
        ``total`` always reflects the true magnitude of a burst regardless of
        the cap — sufficient for an observation-only audit, and it keeps the
        persisted ``url_audit_seen`` parameter bounded.
        """
        domain = Domain(
            [
                ("type", "=", "binary"),
                ("url", "!=", False),
                ("public", "=", False),
            ]
        )
        # Report the true total but only materialize/track the lowest-id
        # window (_URL_AUDIT_WINDOW): the WARNING fires for newly-seen rows in
        # that window, while the logged `total` still conveys the magnitude of a
        # burst (e.g. a controller leaking url into vals) even when it exceeds
        # the window.
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
        follows its store key (location switches do not migrate rows), so a
        switched-away backend still owns keys to collect. The previous
        single-backend dispatch left the file checklist unswept forever
        while ``location='db'``.

        :return: ``False`` if any backend skipped its run (e.g. lock not
            available — retried on the next autovacuum), else ``None``
        """
        # snapshot the registry before any backend commits; the loop itself
        # issues no DB statement, preserving each backend's freedom to make
        # LOCK the first statement of its own fresh transaction
        skipped = False
        for backend_cls in tuple(STORAGE_BACKENDS.values()):
            if backend_cls(self.env).autovacuum() is False:
                skipped = True
        return False if skipped else None

    @api.autovacuum
    def _gc_stale_filestore_temps(self) -> None:
        """Remove orphaned temp files left in the filestore ``tmp/`` directory.

        :meth:`_file_write_stream` streams an upload into ``tmp/stream-<uuid>``
        (and :meth:`_file_write` stages buffered content in ``tmp/write-<uuid>``)
        for the whole write, then atomically moves it into its content-addressed
        shard path (or unlinks it on a dedup hit / error). A worker killed
        mid-write leaves the temp behind — and the content GC never sees it, as
        it only walks the checklist, not ``tmp/``. Sweep entries older than
        :attr:`_FILESTORE_TMP_MAX_AGE`, long past any in-flight upload, so a
        crash-prone deployment cannot accumulate dead temps unbounded.

        Registered as ``@api.autovacuum`` so the nightly cron runs it; the
        ``tmp/`` dir is a local-filestore concept, but the early return below
        makes it a safe no-op under ``db`` (or any keyed) storage. Pure
        filesystem work (no DB, no checklist), so it needs no table lock. Uses
        ``mtime``: an actively-streamed temp keeps a recent mtime.
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
                # a concurrent move/unlink (or a permission glitch) on one
                # entry must not abort the sweep of the rest
                _logger.info("temp gc could not remove %s", entry, exc_info=True)
        if removed:
            _logger.info("filestore temp gc: removed %d stale temp file(s)", removed)

    def _gc_checklist(
        self, limit: int | None = None, grace: float | None = None
    ) -> dict[str, Path]:
        """Return ``{fname: checklist_path}`` from the GC checklist directory.

        Pure filesystem scan (no DB), so it can run outside the table lock.

        :param int | None limit: stop scanning after this many entries — the
            sweep consuming the result runs under a SHARE MODE table lock, so
            its size bounds the lock hold time (see :attr:`_GC_MAX_ENTRIES`).
            ``None`` scans everything.
        :param float | None grace: skip markers younger than this many
            seconds; they stay on disk for a later run. Defaults to
            :attr:`_GC_CHECKLIST_GRACE` — the age gate keeping the sweep away
            from content whose transaction may not have flushed its INSERT
            yet (IRA-G1); see that attribute for the race. Pass ``0`` to
            sweep everything regardless of age (tests, manual maintenance).
        :rtype: dict
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
                # Use relative_to() so fname is correct regardless of nesting depth.
                # dirpath.name would only work for a 2-level structure.
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

    def _gc_file_store_unsafe(self, checklist: dict[str, Path] | None = None) -> None:
        # The caller may pass a checklist scanned before taking the lock; tests
        # and direct callers omit it and scan here (IRA-P2-3).
        if checklist is None:
            checklist = self._gc_checklist()

        # Clean up the checklist. The checklist is split in chunks and files are garbage-collected
        # for each chunk.
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
                        # Keep the checklist entry so the file is retried on
                        # the next GC run instead of being permanently orphaned.
                        continue
                with contextlib.suppress(OSError):
                    Path(filepath).unlink()

        _logger.info("filestore gc %d checked, %d removed", len(checklist), removed)

    def _set_attachment_data(self, asbytes: Callable[[Any], bytes]) -> None:
        # Re-check serving permission on content changes too (IRA-P1-1).
        # `write` only re-runs _check_serving_attachments when url/type change,
        # but swapping the *content* of a served binary+url attachment changes
        # what ir.http._serve_fallback hands out. Both content paths converge
        # here (`write({'raw': ...})` and `record.raw = ...` via the inverse,
        # which writes as sudo and bypasses the `write` override), so this is
        # the single place that covers them. No-op for non-served attachments.
        self._check_serving_attachments()
        old_fnames = []
        wrote_content = False
        backend = self._storage_backend()
        # Single-slot memo of the previous record's derived values: a
        # multi-record `write({'raw': X})` hands EVERY record the same cached
        # bytes object (super().write puts one converted value in the field
        # cache; _inverse_raw reads it back per record), so re-hashing,
        # re-indexing and re-writing X once per row is pure waste — the memo
        # also writes each distinct payload exactly once (the persist now
        # happens inside _get_datas_related_values). One slot rather
        # than a map keyed on id(bin_data): holding the single reference keeps
        # the identity check sound (the object cannot die and its id be
        # recycled), and the base64 path — which decodes a DISTINCT object per
        # record and thus never hits — is not pinned into O(total bytes) of
        # retained payloads.
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
                # The content was already persisted (once per distinct payload)
                # by _get_datas_related_values above. Writing it as we go — and
                # letting each `bin_data` be released — keeps peak memory flat
                # instead of buffering every record's content until the end.
                # It is safe: the flush below still runs before any OLD key is
                # deleted, so in-use content is never GC'd mid-write.
                wrote_content = True

        if old_fnames or wrote_content:
            # before touching external storage, flush so the rows reference
            # the new content before any old key is marked for deletion
            # (prevents the GC from collecting in-use content mid-transaction)
            self.flush_recordset(["checksum", "store_fname"])
        for fname in old_fnames:
            # key-axis dispatch: the old content may live in a backend other
            # than the configured one (location switches don't migrate rows).
            # Also marks old files for GC under db location, which the
            # previous use_filestore gate silently skipped (orphaned files).
            self._storage_delete(fname)

    def _get_datas_related_values(
        self,
        data: bytes,
        mimetype: str,
        backend: AttachmentStorage | None = None,
        checksum: str | None = None,
    ) -> dict[str, Any]:
        """Derive the content columns for *data* AND persist its bytes.

        ``backend.write`` both stores the payload and returns its store
        fragment (``store_fname``/``db_datas``) in one step — the persisted
        key is the write's own return value, so there is no parallel key
        derivation to keep in sync with what was actually written. Callers
        must therefore NOT persist the content a second time; the write is
        idempotent (content-addressed) but a redundant call re-reads the whole
        stored file for the SHA-1 collision check.
        """
        # Callers that already hashed *data* (create()'s batch memo key) pass
        # the checksum to skip a second SHA-1 pass over the same bytes.
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
            # content location (store_fname/db_datas) is backend policy;
            # backend.write persists the bytes (mkdir, SHA-1 collision check,
            # write) and returns the fragment in the same step.
            **backend.write(data, checksum),
        }

    @api.model
    def _get_image_autoresize_config(self) -> tuple[list[str], int, int, int]:
        """Parse the image-autoresize system parameters, with guards.

        Misconfigured parameters must never crash an upload: an invalid
        resolution disables the resize, an invalid quality falls back to 80.

        :return: ``(subtypes, max_width, max_height, jpeg_quality)``;
            ``max_width``/``max_height`` are 0 when autoresize is disabled
        :rtype: tuple
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
        raw_quality = ICP("base.image_autoresize_quality", 80)
        try:
            quality = int(raw_quality)
        except TypeError, ValueError:
            _logger.warning(
                "Invalid base.image_autoresize_quality value: %r, using 80",
                raw_quality,
            )
            quality = 80
        return subtypes, max_width, max_height, quality

    def _postprocess_contents(self, values: dict[str, Any]) -> dict[str, Any]:
        # Reuse the mimetype the sole caller (_check_contents) already resolved;
        # only sniff it here when this hook is invoked standalone. Skips a
        # redundant second _mimetype_from_values pass on every create/write
        # (_mimetype_from_values always returns a truthy type, so a value set
        # upstream is never re-derived).
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
            # Autoresize is best-effort and must never 500 an upload. Decode
            # errors are wrapped as UserError by ImageProcess.__init__, but
            # resize()/image_quality() leak PIL-native exceptions that the old
            # UserError-only catch let escape: a truncated image raises OSError
            # (when PIL's ImageFile.LOAD_TRUNCATED_IMAGES is off — a global set
            # as an import side-effect of ir_actions_report, not here), and an
            # oversized one raises DecompressionBombError during the
            # verify_resolution=False decode, where PIL's guard is the only
            # check. Swallow these and keep the original bytes unprocessed; the
            # payload is never fully decoded, so this cannot blow up memory.
            _logger.info("Post processing ignored : %s", e)
        return values

    @api.model
    def _index(
        self, bin_data: bytes, file_type: str, checksum: str | None = None
    ) -> str | None:
        """Extract the searchable text content of *bin_data* (text types only).

        Python implementation of the unix command ``strings``.

        :param bytes bin_data: the binary content
        :param str file_type: the attachment mimetype
        :param checksum: unused here; hook parameter for caching overrides
        :return: the index content, or ``None`` for non-text content
        :rtype: str | None
        """
        # compute index_content only for text type
        if file_type and file_type.startswith("text/"):
            # Decode as UTF-8, then keep runs of printable characters, dropping
            # control characters (the binary-noise markers). Scanning the
            # decoded TEXT — not the raw bytes — is what keeps accented and
            # non-Latin words whole: the previous byte-class [\x20-\x7E] split
            # every multi-byte char, silently shredding e.g. "configuración"
            # into "configuraci"/"n" and crippling full-text search in non-ASCII
            # deployments. Output is byte-for-byte identical to the old code for
            # pure-ASCII content (verified across the full 0-255 byte range).
            text = bin_data[: self._INDEX_MAX_BYTES].decode("utf-8", errors="ignore")
            words = re.findall(r"[^\x00-\x1f\x7f-\x9f]{4,}", text)
            return "\n".join(words)
        return None

    @api.model
    def _index_read_size(self, mimetype: str) -> int | None:
        """How many bytes of stored content to read back to feed :meth:`_index`.

        Only used by the streaming create path (:meth:`_create_from_stream`),
        which wrote the payload WITHOUT buffering it and must now decide how
        much to read back for index extraction:

        * ``0`` — skip the read entirely (nothing this backend indexes);
        * a positive int — read a bounded prefix;
        * ``None`` — read the whole stored content.

        Base indexes only ``text/*`` and caps at ``_INDEX_MAX_BYTES`` (see
        :meth:`_index`), so every other mimetype reads NOTHING — the previous
        code always read a ``_INDEX_MAX_BYTES`` prefix and handed it to
        ``_index``, which then returned ``None`` for non-text, wasting a read of
        up to that size from (possibly remote) storage on every binary upload.

        Overrides that parse more (``attachment_indexation`` reads whole
        pdf/office documents) widen this for their own mimetypes. The buffered
        create path already hands those overrides the full content, so reading
        it back in full here keeps the two paths consistent — a streamed
        document larger than ``_INDEX_MAX_BYTES`` otherwise got only a truncated
        prefix and silently lost its full-text index.

        :param str mimetype: the resolved attachment mimetype
        :rtype: int | None
        """
        if mimetype and mimetype.startswith("text/"):
            return self._INDEX_MAX_BYTES
        return 0

    @api.model
    def get_serving_groups(self) -> list[str]:
        """An ir.attachment record may be used as a fallback in the
        http dispatch if its type field is set to "binary" and its url
        field is set as the request's url. Only the groups returned by
        this method are allowed to create and write on such records.
        """
        return ["base.group_system"]

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
                # By default a user cannot write on itself, despite the list of
                # writable fields (e.g. inserting an image into its own image
                # signature), so _filtered_access would needlessly drop the
                # user's OWN record. Exclude it from the check rather than
                # bypassing the whole group only when it is the SOLE record in
                # the batch — a batch mixing the self record with another user's
                # otherwise lost the bypass and wrongly denied the self record
                # too (IRA review #4).
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

        For each linked model, an attachment is reachable when the comodel
        record it points to (``res_id``) is itself accessible — expressed as a
        subquery on the comodel's own ``_search`` — and, for a non-system user
        reading field-backed attachments, when ``res_field`` names a readable
        binary/relational field on that comodel. Only used on the small-model
        path (``len(res_model_names) <= _SEARCH_MODEL_DOMAIN_LIMIT``); the
        fetch-and-filter fallback in :meth:`_fetch_accessible_ids` covers the
        rest. Extracted from :meth:`_search` so the per-model access logic can
        be exercised on its own.

        :param domain: the optimized search domain (read for the res_id restriction)
        :param res_model_names: the restricted ``res_model`` values
        :param bool disable_binary_fields_attachments: whether ``res_field`` is
            already forced to ``False`` upstream (skips the field-ACL clause)
        :return: the OR of the per-model subdomains (``Domain.FALSE`` if none)
        :rtype: Domain
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
                    # `codomain=codomain` binds THIS iteration's value rather than
                    # the loop variable. DEFENSIVE only: Domain.map_conditions is
                    # eager (it applies the lambda before the loop advances), so
                    # the late-binding pitfall cannot bite today — no test can
                    # distinguish its presence (verified by mutation). The default
                    # arg keeps the closure correct should map_conditions ever
                    # become lazy. See IRA-M1 (an unfalsifiable invariant).
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

        # We do not have a small restriction on res_model. We still need to
        # support other queries such as: `('id', 'in' ...)`.
        # Restrict with domain and add all attachments linked to a model.
        # Batch the fetch instead of materializing every matching row's
        # security fields at once: for a non-system search over a large
        # attachment table that single fetch was O(table) in memory
        # (IRA-P1-3). Same order, same access filter, same offset — only
        # the peak memory changes.
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

    def _fetch_accessible_ids(
        self, domain: Domain, order: str | None, bound: int | None
    ) -> list[int]:
        """Collect ids readable by the current user, fetching by batches.

        When no ``order`` is requested, batches advance by keyset pagination
        on a deterministic default order — constant cost per batch, whereas
        OFFSET re-scans all previously skipped rows and made the whole scan
        quadratic on large tables (IRA-B5). A caller-specified ``order`` falls
        back to OFFSET batching since its sort keys are arbitrary, but is first
        made total by appending the unique ``id`` — otherwise ties straddling a
        batch boundary could be skipped or duplicated across the separate batch
        queries (an access-control correctness hazard, not just a perf one).

        :param domain: optimized search domain, without offset/limit
        :param order: requested order, or None for the keyset default
        :param bound: stop once this many ids are collected (None: collect all)
        :return: the accessible ids
        :rtype: list
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
            # Caller-supplied order may carry no unique tiebreaker; OFFSET
            # pagination over a non-total order can skip or duplicate rows
            # across batches — PostgreSQL is free to order ties differently
            # between the separate batch queries. Append the unique `id` so the
            # multi-batch sort is total and stable. `keyset` stays None: an
            # arbitrary sort needs a per-order seek predicate, so this path
            # keeps OFFSET batching (a known cost for very large ordered scans).
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
        # Write the new tokens through super(): an access_token write cannot
        # change serving eligibility or content, so re-entering the public
        # write() override (serving re-check + content normalization +
        # res_field ACL) once per record is pure overhead. super().write still
        # enforces the write ACL and the access_token field-group ACL exactly
        # as the override's super() call did. Tokens are unique per row, so the
        # writes cannot collapse into a single UPDATE.
        for attachment in self.browse(new_tokens):
            super(IrAttachment, attachment).write(
                {"access_token": new_tokens[attachment.id]}
            )
        return tokens

    def _get_raw_access_token(self) -> str:
        """Return a scoped access token for the `raw` field. The token can be
        used with `ir_binary._find_record` to bypass access rights.

        :rtype: str
        """
        self.ensure_one()
        return limited_field_access_token(self, "raw", scope="binary")

    @api.model
    def create_unique(self, values_list: list[dict[str, Any]]) -> list[int]:
        """Create attachments, deduplicating by checksum/size/mimetype.

        Accepts content as base64 ``datas`` or raw ``raw`` (bytes/str), like
        :meth:`create` (``raw`` wins by key presence). The create() content
        pipeline (mimetype guess, XML neutralization, image autoresize) runs
        ONCE per value in the probe phase, so the dedup key is the checksum of
        the bytes that will actually be stored. Hashing the pre-pipeline bytes
        instead made an autoresized image miss an already-stored copy and
        create a duplicate row on every separate call (the content-addressed
        file still deduped; only the rows did not). The pipeline is cheap for
        the common inputs — webp is skipped on a magic-byte check and an
        in-bounds image is a header-only parse — and a full decode happens only
        for an oversized image, whose resized bytes are then reused so create()
        does not redo the work.

        :raise UserError: if a value is not base64-encoded or omits ``mimetype``

        .. note::
            The dedup search runs as ``sudo()`` so it can match a
            filestore-shared file across companies; the returned id may
            therefore belong to another company. Reading that id is still
            ACL-gated, so this leaks no content (IRA-C2).
        """
        # Phase 1: normalize content (raw|datas), apply the create() content
        # pipeline, and key the dedup on the FINAL (post-pipeline) checksum.
        entries: list[tuple[dict, str, int, str]] = []
        for values in values_list:
            if "mimetype" not in values:
                raise UserError(_("Attachment is missing its mimetype."))
            vals = {k: v for k, v in values.items() if k != "datas"}
            if "raw" in values:
                raw = values["raw"] or b""
                vals["raw"] = raw.encode() if isinstance(raw, str) else raw
            else:
                vals["raw"] = self._decode_datas(values.get("datas"))
            vals = self._check_contents(vals)
            checksum = self._content_checksum(vals["raw"])
            entries.append((vals, checksum, len(vals["raw"]), vals["mimetype"]))

        # Phase 2: find one existing id per (checksum, file_size, mimetype).
        # Aggregate instead of materializing EVERY row sharing a checksum: a
        # content hash linked to N attachments (the same file referenced from
        # many records) otherwise fetched all N rows just to keep one, making
        # this O(rows-with-that-checksum) on a hot file. id:max reproduces the
        # previous "newest match" choice exactly — the old search ran in the
        # model's default `id desc` order and setdefault kept the first row.
        # skip_res_field_check: the dedup must also match attachments backing
        # binary fields, which _search hides by default.
        all_checksums = list({cs for _, cs, _, _ in entries})
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

        # Phase 3: batch-create the misses (in-batch duplicates dedup to the
        # first occurrence), then resolve ids in input order. The content
        # pipeline already ran in phase 1, so skip a second autoresize pass.
        to_create = []
        new_index_by_key: dict[tuple, int] = {}
        for vals, checksum, file_size, mimetype in entries:
            key = (checksum, file_size, mimetype)
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
                existing
                if (existing := existing_by_key.get((checksum, file_size, mimetype)))
                else created[new_index_by_key[checksum, file_size, mimetype]].id
            )
            for _vals, checksum, file_size, mimetype in entries
        ]

    def _generate_access_token(self) -> str:
        return str(uuid.uuid4())

    @api.model
    def action_get(self) -> dict[str, Any]:
        return self.env["ir.actions.act_window"]._for_xml_id("base.action_attachment")

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

    def _from_request_file(self, file: Any, *, mimetype: str, **vals: Any) -> Self:
        """
        Create an attachment out of a request file

        :param file: the request file
        :param str mimetype:
            * "TRUST" to use the mimetype and file extension from the
              request file with no verification.
            * "GUESS" to determine the mimetype and file extension on
              the file's content. The determined extension is added at
              the end of the filename unless the filename already had a
              valid extension.
            * a mimetype in format "{type}/{subtype}" to force the
              mimetype to the given value, it adds the corresponding
              file extension at the end of the filename unless the
              filename already had a valid extension.
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

    def _should_stream_upload(self, mimetype: str) -> bool:
        """Whether an upload of *mimetype* can be streamed to storage.

        Streaming keeps peak memory flat but bypasses the in-memory content
        pipeline, so it is used only when no transform rewrites the bytes. The
        one such transform is image autoresize (:meth:`_postprocess_contents`);
        everything else needs at most a prefix (mimetype sniff, ``_index``) or
        just metadata. So buffer only an image that autoresize may shrink, and
        stream everything else.

        :param str mimetype: the resolved upload mimetype
        :rtype: bool
        """
        if self.env.context.get("image_no_postprocess"):
            return True
        maintype, _, subtype = (mimetype or "").partition("/")
        if maintype != "image":
            return True
        subtypes, max_width, _height, _quality = self._get_image_autoresize_config()
        return not (max_width and subtype in subtypes)

    def _create_from_stream(
        self, fileobj: Any, *, name: str, mimetype: str, **vals: Any
    ) -> Self:
        """Create a binary attachment by streaming *fileobj* into storage.

        The row is created first (running create()'s access checks and post-add
        hooks) WITHOUT content, then the payload is streamed into the configured
        backend and the derived metadata written back internally — mirroring how
        :meth:`copy` sets content metadata via a ``super()`` write. Peak memory
        stays O(chunk), unlike the buffered ``raw=file.read()`` path.

        :param fileobj: a binary file-like supporting ``read(size)``
        :rtype: ir.attachment
        """
        record = self.create(
            {"name": name, "type": "binary", "mimetype": mimetype, **vals}
        )
        # Resolve the write-side backend once and stream the payload into it.
        store_values = self._storage_backend().write_stream(fileobj)
        # index_content from the stored content. _index_read_size decides how
        # much to read back for THIS mimetype: 0 skips the read entirely (the
        # common binary case base does not index — no wasted round-trip to
        # storage), a bounded prefix for text, or the whole file for backends
        # that parse documents (attachment_indexation). Passing the checksum
        # lets such backends share their index cache with the buffered path,
        # whose content is identical whenever the read is full.
        read_size = self._index_read_size(record.mimetype)
        index_content = None
        if read_size != 0:
            content = b""
            readable = True
            if store_values.get("store_fname"):
                content = self._backend_for_key(store_values["store_fname"]).read(
                    store_values["store_fname"], read_size
                )
                if not content and store_values["file_size"]:
                    # A store key is only ever set for NON-empty content, so an
                    # empty read-back of the just-streamed payload means the
                    # stored file is missing or unreadable (the backend swallows
                    # the I/O error and returns b"") — not legitimately empty.
                    # Don't stamp an index derived from the wrong (empty) bytes;
                    # _compute_raw and _migrate key off the same
                    # empty-read-on-non-empty-row signal.
                    _logger.warning(
                        "Unreadable stored content for attachment %s "
                        "(store_fname=%s); skipping index extraction",
                        record.id,
                        store_values["store_fname"],
                    )
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
            # key-axis dispatch: the content follows its store key, not the
            # configured location (a file-stored row must keep streaming
            # from disk after the location switches to db)
            return self._backend_for_key(self.store_fname).to_stream(self, stream)

        if self.db_datas:
            stream.type = "data"
            stream.data = self.raw
            stream.last_modified = self.write_date
            stream.size = len(stream.data)

        elif self.url:
            # When the URL targets a file located in an addon, assume it
            # is a path to the resource. It saves an indirection and
            # stream the file right away.
            # `request` may be unbound here (cron, server-side report image
            # resolution): the store_fname branch above already guards for it,
            # so mirror that — `request.httprequest` on the empty proxy raises.
            host = request.httprequest.environ.get("HTTP_HOST", "") if request else ""
            static_path = root.get_static_file(self.url, host=host)
            if static_path:
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

        Storage modules (e.g. ``cloud_storage``) override this to download
        the remote payload and convert the record to ``type='binary'``.
        A plain ``url`` attachment has no retrievable payload, which is an
        expected condition, not an error — hence a ``False`` return rather
        than the exception this method historically raised (the only
        caller, ``ir_actions_report._prepare_local_attachments``, logged it
        at ERROR level on every report render touching a URL attachment).

        :return: whether the attachment now holds local binary content
        :rtype: bool
        """
        self.ensure_one()
        return self.type == "binary"

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
        # deterministic for a fixed comodel/field/operation/user, so a batch of
        # attachments backing the same field (the common list-view case) need
        # only evaluate it once instead of per row.
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
                    # Field ACL must be evaluated on the comodel that declares
                    # the field: subclasses override _has_field_access (e.g.
                    # res.users grants self-read on its own fields). Checking it
                    # on self (ir.attachment) silently bypasses that override —
                    # both _search and _check_res_field_access use the comodel.
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

    @api.model
    def _is_xml_like_mimetype(self, mimetype: str) -> bool:
        """Whether *mimetype* denotes script-bearing markup served inline.

        HTML/XHTML/HTA and the XML family (``svg+xml``, ``text/xml``,
        ``*+xml``) can carry active content that a browser executes when an
        attachment is served from the Odoo origin, so they are neutralized to
        ``text/plain`` for users not trusted to author views (see
        :meth:`_check_contents`).

        Matching is on the mimetype's SUBTYPE, not a substring of the whole
        string. The previous ``"ht" in mimetype`` test false-matched unrelated
        types whose name merely contains those letters — e.g. ``text/richtext``,
        ``application/vnd.ibm.rights-management`` ("rights"),
        ``application/x-silverlight`` ("silverlight") and the zip-based
        ``application/vnd.belightsoft.lhzd+zip`` ("belightsoft") — silently
        rewriting their mimetype to ``text/plain`` on upload.

        :param str mimetype: a lowercase mimetype (``maintype/subtype``)
        :rtype: bool
        """
        # Office OpenXML types carry "xml" in their name but are zip
        # containers, not markup — never neutralize them. (Subtype matching
        # already excludes them; this stays as an explicit, cheap guard.)
        if mimetype.startswith("application/vnd.openxmlformats"):
            return False
        subtype = mimetype.partition("/")[2]
        return (
            "html" in subtype  # text/html, application/xhtml+xml, html-* variants
            or subtype in {"hta", "xml"}  # HTML App, text/xml, application/xml
            or subtype.endswith("+xml")  # svg+xml, mathml+xml, atom+xml, ...
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

    def _is_remote_source(self) -> bool:
        self.ensure_one()
        return bool(
            self.url
            and not self.file_size
            and self.url.startswith(("http://", "https://", "ftp://"))
        )
