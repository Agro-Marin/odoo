import base64
import binascii
import contextlib
import functools
import hashlib
import logging
import mimetypes
import re
import uuid
from collections import defaultdict
from datetime import timedelta
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from odoo import _, api, fields, models, modules
from odoo.exceptions import (
    AccessError,
    MissingError,
    UserError,
    ValidationError,
)
from odoo.fields import Domain
from odoo.http import Stream, request, root
from odoo.libs.constants import PREFETCH_MAX
from odoo.libs.filesystem.mimetypes import (
    MIMETYPE_HEAD_SIZE,
    _olecf_mimetypes,
    fix_filename_extension,
    guess_mimetype,
)
from odoo.orm._typing import ValuesType
from odoo.orm.primitives import COLLECTION_TYPES
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
    for condition in (
        domain.map_conditions(
            lambda cond: (
                cond
                if cond.field_expr == field_name and cond.operator in ("in", "=")
                else Domain.TRUE
            )
        )
        .optimize(model)
        .iter_conditions()
    ):
        # Normalize '=' to a list for uniform handling by callers
        if condition.operator == "=":
            return [condition.value]
        if isinstance(condition.value, COLLECTION_TYPES):
            return condition.value
        return None
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

    # Grace window (days) before superseded ESM artifacts are vacuumed by
    # _gc_esm_assets; operators override via ``web.esm.gc_grace_days``.
    _ESM_GC_GRACE_DAYS = 7

    # Cap the bytes scanned and stored by _index. A large text upload would
    # otherwise spill an unbounded index_content into the DB (and spike memory
    # building the full match list); full-text search only needs a prefix.
    # Override per subclass to index more/less.
    _INDEX_MAX_BYTES = 4 * 1024 * 1024

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

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        # {res_model: {res_id}} for the batched comodel access check below
        model_and_ids = defaultdict(OrderedSet)

        # remove computed fields depending on datas
        vals_list = [
            {
                key: value
                for key, value in vals.items()
                if key not in ("file_size", "checksum", "store_fname")
            }
            for vals in vals_list
        ]
        checksum_raw_map = {}
        # Resolve the write-side backend once for the whole batch: it feeds
        # both the store-key fragment (_get_datas_related_values) and the
        # filestore write below, instead of being rebuilt per attachment.
        backend = self._storage_backend()

        for values in vals_list:
            # 'datas' must be popped in all cases to bypass `_inverse_datas`
            has_raw = "raw" in values
            has_datas = "datas" in values
            datas = values.pop("datas", None)
            if has_raw:
                # key presence wins over truthiness, mirroring write(): an
                # explicit empty 'raw' beats a 'datas' payload (IRA-A3)
                raw = values["raw"] or b""
                values["raw"] = raw.encode() if isinstance(raw, str) else raw
            elif has_datas:
                values["raw"] = base64.b64decode(datas or b"")

            # _check_contents mutates `values` in place and returns it; even if
            # an override forks a new dict here, create() stays correct because
            # _inverse_raw re-derives content metadata post-create (see
            # test_a1_create_is_robust_to_new_dict_override).
            values = self._check_contents(values)
            if has_raw or has_datas:
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
                values.update(
                    self._get_datas_related_values(raw, values["mimetype"], backend)
                )
                if raw:
                    # only non-empty content needs a filestore write
                    checksum_raw_map[values["checksum"]] = raw

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
        records = super().create(vals_list)
        for checksum, raw in checksum_raw_map.items():
            backend.write(raw, checksum)
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
                for record in self:
                    self._check_res_field_access(record.res_model, res_field)
        # Normalize content values like create() does: 'raw' takes precedence
        # over 'datas', and str content is encoded. Without this, both
        # inverses run in vals key order and the *last* key silently wins —
        # the opposite of create() for {'raw': ..., 'datas': ...} — and the
        # base64 payload is decoded up to three times along the write path.
        if "datas" in vals:
            datas = vals.pop("datas")
            if "raw" not in vals:
                vals["raw"] = base64.b64decode(datas or b"")
        if isinstance(vals.get("raw"), str):
            vals["raw"] = vals["raw"].encode()
        # remove computed fields depending on datas
        for field in ("file_size", "checksum", "store_fname"):
            vals.pop(field, False)
        if "mimetype" in vals or "raw" in vals:
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
                if not attachment.store_fname:
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
        #
        # Deleting an asset-bundle attachment must also drop the "assets"
        # ormcache, which stores rendered asset nodes embedding the bundle URL:
        # a cached node that outlives its attachment is a hard 404 on the next
        # request (the ESM serve path, unlike the classic /web/assets
        # controller, has no on-the-fly rebuild). clear_cache() also signals
        # other workers. The hot build-time version rotation goes through
        # _unlink_attachments' raw SQL, which bypasses this on purpose to avoid
        # cross-worker thrash and only ever drops already-superseded versions.
        clear_assets = any(
            url and url.startswith("/web/assets/") for url in self.mapped("url")
        )
        to_delete = OrderedSet(
            attach.store_fname for attach in self if attach.store_fname
        )
        res = super().unlink()
        for file_path in to_delete:
            # key-axis dispatch: the content follows its store key, not the
            # currently configured location
            self._storage_delete(file_path)
        if clear_assets:
            self.env.registry.clear_cache("assets")

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
                attach.raw = attach._backend_for_key(attach.store_fname).read(
                    attach.store_fname
                )
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
                raw = base64.b64decode(values["datas"])
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
        if self.type != "binary" or self.mimetype != "application/pdf":
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
            # image_no_postprocess: a storage-*location* migration must not
            # re-run autoresize and silently mutate bytes/checksum. mimetype is
            # passed to avoid recomputation.
            attach.with_context(image_no_postprocess=True).write(
                {"raw": raw, "mimetype": attach.mimetype}
            )
            # Drop the just-written binary from cache so memory stays flat over a
            # filestore-wide migration instead of growing O(total bytes) (P2-6).
            attach.invalidate_recordset()
            if can_commit and index % 100 == 0:
                self.env.cr.commit()

    @api.model
    def _sanitize_store_path(self, path: str) -> str:
        """Neutralize traversal vectors in a store path (dots, colons, leading separators)."""
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
        if not Path(full_path).exists():
            # Write to a unique temp file in the same shard dir, then atomically
            # replace into place. A crash thus never leaves a truncated file at
            # the content-addressed path — which would otherwise fail every
            # future _same_content check with a spurious collision UserError and
            # block re-uploads of that content permanently. replace() is atomic
            # within a filesystem, so no cross-fs copy is involved.
            tmp_path = Path(f"{full_path}.tmp-{uuid.uuid4().hex}")
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

    def _mark_for_gc(self, fname: str) -> None:
        """Add ``fname`` in a checklist for the filestore garbage collection."""
        # fname is sanitized like _full_path does (path-traversal blocked)
        checklist_dir = Path(self._full_path("checklist"))
        full_path = checklist_dir / self._sanitize_store_path(fname)
        if not full_path.exists():
            with contextlib.suppress(OSError):
                full_path.parent.mkdir(parents=True, exist_ok=True)
            with full_path.open("ab"):
                pass

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
        """
        domain = Domain(
            [
                ("type", "=", "binary"),
                ("url", "!=", False),
                ("public", "=", False),
            ]
        )
        # Report the true total but only materialize/track a bounded window, so
        # a burst (e.g. a controller leaking url into vals) is surfaced rather
        # than masked by the display cap.
        total = self.sudo().search_count(domain)
        if not total:
            return
        suspicious = self.sudo().search(domain, order="id", limit=20)
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

    @api.model
    def _esm_asset_domain(self) -> Domain:
        """Return the domain identifying server-generated web-asset rows.

        The identity shared by the asset GC and bundle regeneration: a public,
        ir.ui.view-owned (``res_id=0``) attachment created by the superuser
        whose ``url`` lives under ``/web/assets/``.

        :rtype: Domain
        """
        return Domain(
            [
                ("public", "=", True),
                ("res_model", "=", "ir.ui.view"),
                ("res_id", "=", 0),
                ("create_uid", "=", api.SUPERUSER_ID),
                ("url", "=like", "/web/assets/%"),
            ]
        )

    @api.autovacuum
    def _gc_esm_assets(self) -> None:
        """Sweep superseded ESM bundle artifacts and aged bridge shims.

        Bundle rebuilds do not delete the previous version inline (the row
        must keep serving in-flight pages, stale CDN HTML and workers that
        have not yet processed the cache-clear signal); this vacuum deletes
        superseded rows once they are older than the grace window, always
        keeping the newest row per artifact name — a stable bundle's only
        row may be years old and must survive.

        Bridge shims (``/web/assets/esm/bridges/<hash>.js``) are
        content-addressed and re-persisted on the next read-write render
        after the cache clear that ``unlink()`` triggers, so age alone is a
        safe criterion for them; a page older than the grace window doing
        its first lazy import of a swept shim 404s until reload — accepted,
        the alternative was unbounded row growth (no other GC path exists).
        """
        get_param = self.env["ir.config_parameter"].sudo().get_param
        try:
            grace_days = int(
                get_param("web.esm.gc_grace_days", self._ESM_GC_GRACE_DAYS)
            )
        except TypeError, ValueError:
            grace_days = self._ESM_GC_GRACE_DAYS
        # Floor at one day: 0/negative makes cutoff >= now and sweeps every
        # bridge (which has no newest-per-name protection) on every run.
        grace_days = max(1, grace_days)
        cutoff = fields.Datetime.now() - timedelta(days=grace_days)

        # Asset rows as created by _save_esm_attachment / _save_esm_sidecar /
        # _persist_bridge_shims. The name suffixes also catch the legacy
        # ``/web/assets/<ver>/<bundle>.esm.js`` layout while excluding the
        # classic ``.min.js`` bundles, which have their own rotation.
        candidates = self.sudo().search(
            self._esm_asset_domain()
            & Domain("write_date", "<", cutoff)
            & Domain.OR(
                [
                    [("url", "=like", "/web/assets/esm/bridges/%")],
                    [("name", "=like", "%.esm.js")],
                    [("name", "=like", "%.esm.js.map")],
                    [("name", "=like", "%.meta.json")],
                ]
            )
        )
        if not candidates:
            return

        bridges = candidates.filtered(
            lambda a: a.url.startswith("/web/assets/esm/bridges/")
        )
        artifacts = candidates - bridges
        stale_artifacts = self.browse()
        if artifacts:
            # The newest row per name is the live version. It must be
            # computed over ALL rows of that name — not just the over-grace
            # candidates — otherwise a superseded row whose successor is
            # younger than the cutoff would pose as "newest" forever.
            live_ids = {
                max_id
                # Same population as `candidates` (minus the grace/suffix
                # filters): a serving-group user could otherwise create a
                # higher-id same-named row that poses as "newest", marking the
                # real bundle stale.
                for _name, max_id in self.sudo()._read_group(
                    self._esm_asset_domain()
                    & Domain("name", "in", list(set(artifacts.mapped("name")))),
                    ["name"],
                    ["id:max"],
                )
            }
            stale_artifacts = artifacts.filtered(lambda a: a.id not in live_ids)

        to_gc = stale_artifacts | bridges
        if to_gc:
            # unlink() handles the filestore entries and, because the URLs
            # are under /web/assets/, clears the "assets" ormcache so the
            # next render re-persists any bridge shim still in use (same
            # content hash, same URL — browser caches stay valid).
            to_gc.unlink()
            _logger.info(
                "GC'd %d stale ESM artifact(s) and %d aged bridge shim(s) "
                "older than %d day(s)",
                len(stale_artifacts),
                len(bridges),
                grace_days,
            )

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

    def _gc_checklist(self) -> dict[str, Path]:
        """Return ``{fname: checklist_path}`` from the GC checklist directory.

        Pure filesystem scan (no DB), so it can run outside the table lock.

        :rtype: dict
        """
        checklist = {}
        checklist_root = Path(self._full_path("checklist"))
        for dirpath, _subdirs, filenames in checklist_root.walk():
            for filename in filenames:
                # Use relative_to() so fname is correct regardless of nesting depth.
                # dirpath.name would only work for a 2-level structure.
                fname = str((dirpath / filename).relative_to(checklist_root))
                checklist[fname] = dirpath / filename
        return checklist

    def _gc_file_store_unsafe(self, checklist: dict[str, Path] | None = None) -> None:
        # The caller may pass a checklist scanned before taking the lock; tests
        # and direct callers omit it and scan here.
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
        checksum_raw_map = {}
        backend = self._storage_backend()

        for attach in self:
            # compute the fields that depend on datas
            bin_data = asbytes(attach)
            vals = self._get_datas_related_values(bin_data, attach.mimetype, backend)
            if bin_data:
                checksum_raw_map[vals["checksum"]] = bin_data

            # take the current store key to possibly garbage-collect it
            if attach.store_fname:
                old_fnames.append(attach.store_fname)

            # write as superuser, as user probably does not have write access
            super(IrAttachment, attach.sudo()).write(vals)

        if old_fnames or checksum_raw_map:
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
        for checksum, raw in checksum_raw_map.items():
            backend.write(raw, checksum)

    def _get_datas_related_values(
        self, data: bytes, mimetype: str, backend: AttachmentStorage | None = None
    ) -> dict[str, Any]:
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
            # content location (store_fname/db_datas) is backend policy.
            # Only the store key is computed here; the storage work (mkdir,
            # SHA-1 collision check, write) happens once in backend.write
            # — doing it here too re-read the existing file end-to-end on
            # every dedup hit (see IRA-P2-1).
            **backend.datas_values(data, checksum),
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
        mimetype = values["mimetype"] = self._mimetype_from_values(values)
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
        except UserError as e:
            # Catch error during test where we provide fake image
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
            words = re.findall(rb"[\x20-\x7E]{4,}", bin_data[: self._INDEX_MAX_BYTES])
            return b"\n".join(words).decode("ascii")
        return None

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
            records = self.env[res_model].browse(res_ids)
            if (
                res_model == "res.users"
                and len(records) == 1
                and self.env.uid == records.id
            ):
                # by default a user cannot write on itself, despite the list of writable fields
                # e.g. in the case of a user inserting an image into his image signature
                # we need to bypass this check which would needlessly throw us away
                continue
            try:
                records = records._filtered_access(operation)
            except MissingError:
                records = records.exists()._filtered_access(operation)
            res_ids.difference_update(records._ids)
            for res_id in res_ids:
                yield res_model, res_id

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
            env = self.with_context(active_test=False).env
            for res_model_name in res_model_names:
                if (comodel := env.get(res_model_name)) is None:
                    continue
                codomain = Domain("res_model", "=", comodel._name)
                comodel_res_ids = condition_values(
                    self,
                    "res_id",
                    domain.map_conditions(
                        # bind the loop's current `codomain` as a default arg so
                        # the closure captures this iteration's value, not the
                        # last one (late-binding closure pitfall). See IRA-M1.
                        lambda cond, codomain=codomain: (
                            codomain & cond if cond.field_expr == "res_model" else cond
                        )
                    ),
                )
                query = comodel._search(
                    Domain("id", "in", comodel_res_ids)
                    if comodel_res_ids
                    else Domain.TRUE
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
                sec_domain |= codomain

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
        quadratic on large tables (IRA-B5). A caller-specified ``order``
        falls back to OFFSET batching since its sort keys are arbitrary.

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
        for attachment in self:
            if attachment.access_token:
                tokens.append(attachment.access_token)
                continue
            access_token = self._generate_access_token()
            attachment.write({"access_token": access_token})
            tokens.append(access_token)
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

        Performs a single batch search for all existing checksums instead of
        one query per attachment.

        :raise UserError: if a value is not base64-encoded or omits ``mimetype``

        .. note::
            The dedup search runs as ``sudo()`` so it can match a
            filestore-shared file across companies; the returned id may
            therefore belong to another company. Reading that id is still
            ACL-gated, so this leaks no content (IRA-C2).
        """
        # Phase 1: decode and compute checksums for all values
        entries: list[tuple[dict, str, int, str, bytes]] = []
        for values in values_list:
            try:
                bin_data = base64.b64decode(values.get("datas", ""))
            except binascii.Error as exc:
                raise UserError(_("Attachment is not encoded in base64.")) from exc
            if "mimetype" not in values:
                raise UserError(_("Attachment is missing its mimetype."))
            checksum = self._content_checksum(bin_data)
            entries.append(
                (values, checksum, len(bin_data), values["mimetype"], bin_data)
            )

        # Phase 2: batch search for existing attachments by checksum.
        # skip_res_field_check: the dedup must also match attachments backing
        # binary fields, which _search hides by default.
        all_checksums = list({cs for _, cs, _, _, _ in entries})
        existing_by_key: dict[tuple, Any] = {}
        if all_checksums:
            for att in (
                self.sudo()
                .with_context(skip_res_field_check=True)
                .search([("checksum", "in", all_checksums)])
            ):
                key = (att.checksum, att.file_size, att.mimetype)
                existing_by_key.setdefault(key, att)

        # Phase 3: batch-create the misses (in-batch duplicates dedup to the
        # first occurrence), then resolve ids in input order
        to_create = []
        new_index_by_key: dict[tuple, int] = {}
        for values, checksum, file_size, mimetype, bin_data in entries:
            key = (checksum, file_size, mimetype)
            if key not in existing_by_key and key not in new_index_by_key:
                new_index_by_key[key] = len(to_create)
                # pass the already-decoded bytes as 'raw' so create() does not
                # re-run base64 decode on the same payload
                to_create.append(
                    {
                        **{k: v for k, v in values.items() if k != "datas"},
                        "raw": bin_data,
                    }
                )
        created = self.create(to_create) if to_create else self.browse()
        return [
            (
                existing.id
                if (existing := existing_by_key.get((checksum, file_size, mimetype)))
                else created[new_index_by_key[checksum, file_size, mimetype]].id
            )
            for _values, checksum, file_size, mimetype, _bin in entries
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

    @api.model
    def regenerate_assets_bundles(self) -> None:
        # Explicit gate (like force_storage): unlink below would already deny
        # non-system users via _check_access, but fail fast and clearly.
        if not self.env.is_admin():
            raise AccessError(_("Only administrators can execute this action."))
        self.search(self._esm_asset_domain()).unlink()
        self.env.registry.clear_cache("assets")

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
        elif all(mimetype.partition("/")):
            filename = fix_filename_extension(file.filename, mimetype)
        else:
            raise ValueError(f"{mimetype=}")

        return self.create(
            {
                "name": filename,
                "type": "binary",
                "raw": file.read(),  # load the entire file in memory :(
                "mimetype": mimetype,
                **vals,
            }
        )

    def _to_http_stream(self) -> Stream:
        """Create a :class:`~Stream`: from an ir.attachment record."""
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
                    comodel = self.env[res_model]
                    field = comodel._fields.get(res_field)
                    if field is None or not comodel._has_field_access(field, operation):
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

    def _check_contents(self, values: dict[str, Any]) -> dict[str, Any]:
        mimetype = values["mimetype"] = self._mimetype_from_values(values)
        xml_like = "ht" in mimetype or (  # hta, html, xhtml, etc.
            "xml" in mimetype  # other xml (svg, text/xml, etc)
            and not mimetype.startswith("application/vnd.openxmlformats")
        )  # exception for Office formats
        force_text = xml_like and (
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
