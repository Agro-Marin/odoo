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
from odoo.libs.filesystem import (
    MIMETYPE_HEAD_SIZE,
    _olecf_mimetypes,
    fix_filename_extension,
    guess_mimetype,
)
from odoo.libs.hashing import (
    ALGO_TAG,
    CONTENT_DIGEST_LEN,
    CONTENT_DIGEST_MAX_LEN,
    content_hash,
    content_hasher,
)
from odoo.tools import (
    OrderedSet,
    config,
    consteq,
    file_open,
    image,
    ormcache,
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

BIN_SIZE_KEYS = {
    "bin_size": False,
    "bin_size_raw": False,
    "bin_size_datas": False,
    "bin_size_db_datas": False,
}


@functools.cache
def _resolve_filestore_root(filestore: str) -> Path:
    """Resolve the filestore root once per path string (cached).

    ``_full_path`` runs on every filestore access and ``Path.resolve()`` costs
    a per-component syscall walk. Re-pointing the root symlink mid-run requires
    a restart.
    """
    return Path(filestore).resolve()


@functools.cache
def _resolve_filestore_dir(filestore: str, name: str) -> Path:
    """Resolve a FIXED filestore subdirectory once per ``(root, name)`` (cached).

    ``tmp/`` and ``checklist/`` are resolved on every filestore write, and unlike
    a store key their names are literals — so the sanitize + ``resolve()`` +
    confinement round-trip of :meth:`IrAttachment._full_path` re-derives a
    constant, at ~22 us a call, twice per write.

    Only the two constants go through here. A store key keeps the full
    round-trip: it is the path content is SERVED from, so the ``resolve()``
    there is what refuses a symlink planted under the filestore, and the same
    caching would hold a stale answer for a path that is different every time
    anyway.
    """
    return _resolve_filestore_root(filestore) / name


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

    db_datas = fields.Binary("Database Data", attachment=False)
    # Derived from the content and never written through the public API
    # (`_normalize_content_vals` drops them). `copy=False` keeps `copy_data`
    # from carrying values `create` only throws away: `copy` re-applies them
    # from the origin for a keyed row, and `create` re-derives them from `raw`
    # for an inline one.
    store_fname = fields.Char("Stored Filename", index=True, copy=False)
    file_size = fields.Integer("File Size", readonly=True, copy=False)
    checksum = fields.Char(
        "Checksum", size=CONTENT_DIGEST_MAX_LEN, readonly=True, copy=False
    )
    mimetype = fields.Char("Mime Type", readonly=True)
    index_content = fields.Text(
        "Indexed Content", readonly=True, prefetch=False, copy=False
    )

    raw = fields.Binary(
        string="File Content (raw)",
        compute="_compute_raw",
        inverse="_inverse_raw",
        bin_size_field="file_size",
    )
    datas = fields.Binary(
        string="File Content (base64)",
        compute="_compute_datas",
        inverse="_inverse_datas",
        bin_size_field="file_size",
    )

    _res_field_idx = models.Index("(res_model, res_field, res_id)")
    _checksum_idx = models.Index("(checksum) WHERE checksum IS NOT NULL")

    _SEARCH_MODEL_DOMAIN_LIMIT = 5

    _SEARCH_MODEL_DISCOVERY_LIMIT = 12

    _URL_AUDIT_WINDOW = 20

    _INDEX_MAX_BYTES = 4 * 1024 * 1024

    _INDEX_MAX_CHARS = 256 * 1024

    _STREAM_CHUNK_SIZE = 128 * 1024

    _COMPARE_BLOCK_SIZE = 65536

    _FILESTORE_TMP_MAX_AGE = 24 * 3600

    _GC_MAX_ENTRIES = 100_000

    _GC_CHECKLIST_GRACE = 24 * 3600

    def _is_attachment_backed_field(self, field: Any) -> bool:
        """Whether *field* is one an ir.attachment row can stand for."""
        return field.type == "binary" or (
            field.relational and field.comodel_name == self._name
        )

    def _check_res_field_valid(self, res_model: str, res_field: str) -> None:
        """Reject a ``res_field`` naming a field no attachment can back.

        ``res_field`` asserts "this row IS field X of record Y". The ORM only
        ever writes it for a ``Binary``/``Image`` field, and every reader relies
        on that — :meth:`ir.binary._record_to_stream` looks the row up by it,
        :meth:`_search_models_security_domain` derives a field ACL from it. But
        nothing enforced it, so a row could claim an ordinary field and each
        reader treated it differently. Widening that domain made the readers
        agree; this makes them agree BY CONSTRUCTION, because the state they
        disagreed about can no longer be written.

        A MISSING ``res_model`` is refused outright, for everyone: the pair is
        what carries the meaning, and a ``res_field`` without one names a field
        of nothing. No reader can resolve such a row — :meth:`Binary.read`
        matches it against no model, :meth:`_check_access` refuses it to
        everyone but the superuser — so it is a leak with a lifetime, not a
        state to tolerate. It became reachable through ``write`` once clearing
        ``res_model`` alone was gated at all (see :meth:`_res_field_targets`),
        where it surfaced as an ``AccessError``; that is the wrong answer to
        "this pair does not make sense".

        An UNKNOWN (rather than missing) ``res_model``, or an unknown field on
        a live model, is left to :meth:`_check_res_field_access` — which already
        refuses it for anyone but the superuser — so that a module being
        uninstalled, or a field mid-removal, does not start raising here.

        :raise ValidationError: if *res_field* names a non-attachment field, or
            is set without a ``res_model``
        """
        if not res_model:
            raise ValidationError(
                _(
                    "An attachment standing for the field %(field)s must name "
                    "the model the field belongs to.",
                    field=res_field,
                )
            )
        comodel = self.env.get(self._as_model_name(res_model))
        field = comodel._fields.get(res_field) if comodel is not None else None
        if field is None or self._is_attachment_backed_field(field):
            return
        raise ValidationError(
            _(
                "%(field)s of %(model)s cannot be backed by an attachment: "
                "res_field must name a binary field.",
                field=res_field,
                model=res_model,
            )
        )

    def _check_res_field_access(self, res_model: str, res_field: str) -> None:
        """Validate a field-backing attachment's target field and write access.

        ``res_field`` is a plain Char with no ``groups``, so mutating it would
        bypass the field-group ACL that ``_check_access`` enforces on read;
        mirror that check at create/write time (IRA-L2). Validity
        (:meth:`_check_res_field_valid`) is checked first and for everyone —
        the superuser included, since it is a data-model invariant rather than a
        permission.

        :raise ValidationError: if *res_field* names a non-attachment field
        :raise AccessError: if the user cannot access the comodel field
        """
        if not res_field:
            return
        self._check_res_field_valid(res_model, res_field)
        if self.env.su or self.env.is_system():
            return
        comodel = self.env.get(self._as_model_name(res_model))
        field = comodel._fields.get(res_field) if comodel is not None else None
        if field is None or not comodel._has_field_access(field, "write"):
            raise AccessError(_("Sorry, you are not allowed to access this document."))

    def _res_field_targets(self, vals: dict[str, Any]) -> OrderedSet:
        """Return the ``(res_model, res_field)`` pairs *vals* would leave behind.

        ``res_field`` only means anything paired with ``res_model``: together
        they assert "this row IS field X of model Y". Either half can move, so
        both have to open the same gate — but only a write naming ``res_field``
        did. A write naming ``res_model`` ALONE re-targeted whatever
        ``res_field`` the rows already carried, and skipped both halves of
        :meth:`_check_res_field_access`:

        * the data-model invariant, so a row created against a binary field
          could be re-pointed at a model where that name is an ordinary field,
          or none at all — exactly the state
          :meth:`_check_res_field_valid` exists to make unreachable;
        * the field-group ACL, which is the whole reason the check exists.
          ``res_field`` is a plain Char with no ``groups``, so the ORM cannot
          gate it (IRA-L2); ``super().write`` gates the rows in their CURRENT
          state and knows nothing of the target they are moving to. A user with
          write access to a record could therefore take a field-backing row of
          their own and make it back a binary field of that record they are not
          allowed to write — supplying its content without ever passing the
          field ACL.

        Rows whose ``res_field`` is (and stays) empty yield a falsy pair, which
        :meth:`_check_res_field_access` returns on immediately, so an ordinary
        re-parenting write pays one iteration over the recordset and nothing else.
        """
        has_model, has_field = "res_model" in vals, "res_field" in vals
        new_model = self._as_model_name(vals["res_model"]) if has_model else None
        if has_model and has_field:
            return OrderedSet([(new_model, vals["res_field"])])
        if has_field:
            return OrderedSet((record.res_model, vals["res_field"]) for record in self)
        if has_model:
            return OrderedSet((new_model, record.res_field) for record in self)
        return OrderedSet()

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

        ``db_datas`` is content too, and is folded in behind ``raw``/``datas``
        rather than passed through to the column. It used to reach ``super()``
        untouched, which made it a way to write content that skips the whole
        pipeline, and it was broken in both directions:

        * on ``create`` it produced a row with content but no ``file_size``, no
          ``checksum`` and no ``index_content``, stored inline whatever
          ``ir_attachment.location`` says — so the size the client is told, the
          ETag :meth:`_to_http_stream` serves and the full-text index are all
          absent for a row that reads back fine, and every downstream reader has
          to tolerate the shape;
        * on ``write`` it was silently DISCARDED. ``store_fname`` wins in every
          reader (:meth:`_stored_content`), so a row that already had a store
          key kept serving its old bytes while Postgres gained a second,
          unreachable copy of the new ones and ``file_size``/``checksum`` went
          on describing the old ones. The write reported success.

        A falsy ``db_datas`` (what ``copy_data`` emits for a filestore-backed
        row) is dropped instead, like the other derived columns: it describes
        where content lives, not that there is none. Clearing content is
        ``raw = b""``.

        Vals carrying no content key at all are left untouched (url rows): not
        treated as empty content (IRA-R1).

        :return: whether *vals* carried content (``raw``, ``datas`` or ``db_datas``)
        """
        has_content = "raw" in vals or "datas" in vals
        datas = vals.pop("datas", None)
        db_datas = vals.pop("db_datas", None)
        if "raw" in vals:
            raw = vals["raw"] or b""
            vals["raw"] = raw.encode() if isinstance(raw, str) else raw
        elif has_content:
            vals["raw"] = self._decode_datas(datas)
        elif db_datas:
            has_content = True
            vals["raw"] = db_datas.encode() if isinstance(db_datas, str) else db_datas
        for field in ("file_size", "checksum", "store_fname", "index_content"):
            vals.pop(field, None)
        return has_content

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        vals_list = [dict(vals) for vals in vals_list]

        self.browse().check_access("create")

        model_and_ids = defaultdict(OrderedSet)
        for values in vals_list:
            if res_field := values.get("res_field"):
                self._check_res_field_access(values.get("res_model"), res_field)
            model_and_ids[self._as_model_name(values.get("res_model"))].add(
                values.get("res_id")
            )
        if any(self._inaccessible_comodel_records(model_and_ids, "write")):
            raise AccessError(_("Sorry, you are not allowed to access this document."))

        backend = self._storage_backend()
        derived_values: dict[tuple[str, str], dict[str, Any]] = {}
        for index, values in enumerate(vals_list):
            has_content = self._normalize_content_vals(values)

            values = vals_list[index] = self._check_contents(values)
            if has_content:
                raw = values.pop("raw")
                memo_key = (self._content_checksum(raw), values["mimetype"])
                if memo_key not in derived_values:
                    derived_values[memo_key] = self._get_datas_related_values(
                        raw, values["mimetype"], backend, checksum=memo_key[0]
                    )
                values.update(derived_values[memo_key])

        records = super().create(vals_list)
        records._check_serving_attachments()
        return records

    def write(self, vals: dict[str, Any]) -> bool:
        """Update the attachments, deriving the content columns from *vals*.

        The checks here cover what ``super().write`` cannot: it gates the
        records in their CURRENT state, so the NEW ``res_model``/``res_id``
        target and the NEW ``res_field`` have no other gate. Writability of the
        attachments themselves is left to that one call — checking it here too
        re-ran the whole comodel resolution of :meth:`_check_access` on every
        write, including writes touching nothing security-relevant.
        """
        if "res_model" in vals or "res_id" in vals:
            model_and_ids = defaultdict(OrderedSet)
            new_model = self._as_model_name(vals.get("res_model"))
            if "res_model" in vals and "res_id" in vals:
                model_and_ids[new_model].add(vals["res_id"])
            else:
                for record in self:
                    model_and_ids[
                        new_model if "res_model" in vals else record.res_model
                    ].add(vals.get("res_id", record.res_id))
            if any(self._inaccessible_comodel_records(model_and_ids, "write")):
                raise AccessError(
                    _("Sorry, you are not allowed to access this document.")
                )
        for res_model, res_field in self._res_field_targets(vals):
            self._check_res_field_access(res_model, res_field)
        has_content = self._normalize_content_vals(vals)
        if has_content or "mimetype" in vals:
            if "mimetype" not in vals:
                vals["mimetype"] = self._mimetype_for_write(vals)
            vals = self._check_contents(vals)
        res = super().write(vals)
        if "url" in vals or "type" in vals:
            self._check_serving_attachments()
        return res

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        if not default.keys() & {"datas", "db_datas", "raw"}:
            for attachment, vals in zip(self._unsized(), vals_list, strict=True):
                if attachment.store_fname:
                    # A keyed row's content is at its store key, which
                    # :meth:`copy` points the copy at; the inline column is
                    # dropped rather than carried over. It is normally empty,
                    # but a legacy row can hold both (a half-finished
                    # migration, a restore) — and since ``db_datas`` became
                    # content, carrying those dead bytes made the copy hash and
                    # write them to the filestore before :meth:`copy` replaced
                    # the key, for a file nothing ever references.
                    vals.pop("db_datas", None)
                elif attachment.checksum or attachment.db_datas:
                    vals["raw"] = attachment.raw
        return vals_list

    def copy(self, default: ValuesType | None = None) -> Self:
        """Copy the rows, pointing each copy at its origin's stored content.

        A filestore-backed copy shares its origin's key instead of round-tripping
        the bytes, so :meth:`copy_data` leaves those rows contentless and they
        are pointed at the key here. Copies sharing one origin key are written
        together: duplicating an attachment set used to cost a write per row for
        values that are identical whenever the rows are.
        """
        new_attachments = super().copy(default)
        if not (default or {}).keys() & {"datas", "db_datas", "raw"}:
            by_content: dict[tuple, list[int]] = defaultdict(list)
            for origin, copied in zip(self, new_attachments, strict=True):
                if origin.store_fname:
                    by_content[
                        origin.store_fname,
                        origin.checksum,
                        origin.file_size,
                        origin.index_content,
                    ].append(copied.id)
            for (fname, checksum, size, index), ids in by_content.items():
                super(IrAttachment, self.browse(ids).sudo()).write(
                    {
                        "store_fname": fname,
                        "checksum": checksum,
                        "file_size": size,
                        "index_content": index,
                        "db_datas": False,
                    }
                )
        return new_attachments

    def unlink(self) -> bool:
        to_delete = OrderedSet(
            attach.store_fname for attach in self if attach.store_fname
        )
        res = super().unlink()
        self._storage_delete_multi(to_delete)
        return res

    @api.depends("res_model", "res_id")
    def _compute_res_name(self) -> None:
        to_compute = self.filtered(lambda a: a.res_model and a.res_id)
        (self - to_compute).res_name = False
        for res_model, attachments in to_compute.grouped("res_model").items():
            if res_model not in self.env:
                for attachment in attachments:
                    attachment.res_name = False
                continue
            res_ids = attachments.mapped("res_id")
            records = self.env[res_model].browse(res_ids).exists()
            records = records._filtered_access("read")
            name_map = {record.id: record.display_name for record in records}
            for attachment in attachments:
                attachment.res_name = name_map.get(attachment.res_id, False)

    @api.depends("store_fname", "db_datas", "file_size")
    def _compute_datas(self) -> None:
        """Encode the content as base64.

        ``raw`` is read UNSIZED even though this compute is skipped whenever
        ``datas`` is itself under ``bin_size``: the two fields have independent
        per-field flags, and ``bin_size_raw`` alone reaches here. It then made
        ``datas`` the base64 of ``b"1.97 Kb"`` — which decodes cleanly, so the
        caller receives a well-formed 7-byte payload instead of the file
        (IRA-Z1). Only ``bin_size``/``bin_size_datas`` may shorten ``datas``,
        and those never run this method.
        """
        for attach in self:
            attach.datas = base64.b64encode(attach._unsized().raw or b"")

    @api.depends("store_fname", "db_datas", "file_size")
    def _compute_raw(self) -> None:
        for attach in self:
            attach.raw = attach._stored_content()

    def _inverse_raw(self) -> None:
        self._set_attachment_data(lambda a: a.raw or b"")

    def _inverse_datas(self) -> None:
        self._set_attachment_data(lambda attach: self._decode_datas(attach.datas))

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

        sec_domain = Domain("public", "=", True)
        res_ids = condition_values(self, "res_id", domain)
        if not res_ids or False in res_ids:
            unlinked = Domain("res_id", "=", False) | Domain("res_model", "=", False)
            if self.env.is_system():
                sec_domain |= unlinked
            else:
                sec_domain |= unlinked & Domain("create_uid", "=", self.env.uid)

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

        domain &= self._scan_prefilter(sec_domain)
        domain = domain.optimize_full(self)
        ordered = bool(order)
        if limit is None:
            result = self._fetch_accessible_ids(domain, order, None)
            return self.browse(result[offset:])._as_query(ordered)
        result = self._fetch_accessible_ids(domain, order, offset + limit)
        return self.browse(result[offset : offset + limit])._as_query(ordered)

    @api.model
    def _backend_for_key(self, fname: str) -> AttachmentStorage:
        """Return the read-side backend owning the store key *fname*.

        Dispatch is by URI scheme (``s3://...``); plain sharded fnames
        belong to the local filestore.
        """
        return backend_for_key(self.env, fname)

    def _content_checksum(self, bin_data: bytes) -> str:
        """Return the content digest of *bin_data* (for content-addressed storage).

        The algorithm is :mod:`odoo.libs.hashing`'s content family (BLAKE3,
        sha1 without the extension); :meth:`_file_store_path` tags the store key
        with it, so digests of different vintages coexist in one filestore.
        """
        return content_hash(bin_data or b"")

    @api.model
    def _is_current_digest(self, checksum: str | bool) -> bool:
        """Whether *checksum* was produced by the digest keys are tagged with.

        Only ``store_fname`` carries algorithm provenance — the ``<algo>/``
        prefix :meth:`_file_store_path` stamps on it. The ``checksum`` column
        carries none, so anything turning a STORED checksum back INTO a store
        key must re-establish it, else the key claims an algorithm its digest
        does not have.

        That is not cosmetic. A ``b3/``-tagged key holding a sha1 digest is
        skipped forever by :meth:`_gc_rehash_legacy_keys` (it already looks
        converged), dedups against nothing — identical content re-uploaded
        lands under its real b3 key, so the filestore keeps two copies of the
        same bytes — and, worst, inherits the trust the tag stands for:
        :meth:`_verify_content_collision` stops byte-comparing dedup hits under
        BLAKE3 precisely because BLAKE3 has no practical collisions, which
        turns that mitigation off for a digest that does.

        The two content digests (``blake3``/``sha1``) differ in length, so
        ``CONTENT_DIGEST_LEN`` tells them apart exactly.
        """
        return bool(checksum) and len(checksum) == CONTENT_DIGEST_LEN

    @api.model
    def _filestore(self) -> str:
        return config.filestore(self.env.cr.dbname)

    @api.model
    def _file_delete(self, fname: str) -> None:
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
        if ALGO_TAG == "s1":
            return checksum[:2] + "/" + checksum
        return f"{ALGO_TAG}/{checksum[:2]}/{checksum}"

    @api.model
    def _file_read(self, fname: str, size: int | None = None) -> bytes:
        """Return the content at local-filestore key *fname*, ``b""`` if unreadable.

        An unresolvable key is a read failure like any other, not a crash: a
        single row whose ``store_fname`` escapes the filestore (a symlink out of
        it, a hand-edited column) raised ``ValueError`` out of ``raw``'s compute
        and 500'd the whole recordset read, while :meth:`FileStorage.to_stream`
        already caught exactly that and degraded. Both readers now return
        nothing and let :meth:`_content_read_back_failed` name the row.
        """
        try:
            full_path = self._full_path(fname)
        except ValueError:
            _logger.exception("_file_read refused the store key %r", fname)
            return b""
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
        tmp_dir = self._filestore_dir("tmp")
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
        """Store *bin_value* under its content-addressed key and return it.

        The GC marker is written BEFORE the content is published, and on both
        the fresh-write and dedup-hit paths. Order matters: the marker is what
        makes a file reclaimable, and the sweep walks the checklist, not the
        filestore. A crash between publishing the file and marking it therefore
        stranded content whose row had rolled back with the transaction — not
        forever (writing the same bytes again takes the dedup branch, which
        marks it) but for as long as nobody re-uploads that exact payload, which
        for a one-off document is indefinitely.

        Reversing the order leaks nothing in exchange: a marker whose file does
        not exist unlinks nothing and is dropped by the next sweep (IRA-G2).
        """
        fname, full_path = self._get_path(bin_value, checksum)
        self._mark_for_gc(fname)
        if not Path(full_path).exists():
            with self._staged_filestore_temp("write") as tmp_path:
                with tmp_path.open("wb") as fp:
                    fp.write(bin_value)
                tmp_path.replace(full_path)
        return fname

    @api.model
    def _file_write_stream(
        self, fileobj: Any, *, chunk_size: int | None = None
    ) -> tuple[str, int, str]:
        """Stream *fileobj* into the filestore, hashing as it goes.

        Chunks *fileobj* to a temp file while updating a running digest, then
        atomically moves it into its content-addressed path (or drops it on a
        dedup hit). Peak memory is one chunk — the streaming counterpart of
        :meth:`_file_write`, which needs the full ``bytes`` up front and whose
        marker-before-publish ordering this shares (IRA-G2).

        :param fileobj: a binary file-like supporting ``read(size)``
        :return: ``(store_fname, file_size, checksum)``; ``store_fname`` is
            ``""`` for empty content (kept inline as db_datas)
        """
        chunk_size = chunk_size or self._STREAM_CHUNK_SIZE
        digest = content_hasher()
        size = 0
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
                tmp_path.unlink(missing_ok=True)
                return "", 0, checksum
            fname, full_path_str = self._get_path(
                None, checksum, source_path=str(tmp_path)
            )
            self._mark_for_gc(fname)
            full_path = Path(full_path_str)
            if full_path.is_file():
                tmp_path.unlink(missing_ok=True)
            else:
                tmp_path.replace(full_path)
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
        """Move every attachment into the currently configured storage.

        The sweep runs as ``sudo()`` because the ACL never gated the migration
        itself — :meth:`_rewrite_stored_content` writes as superuser — only
        which rows it FOUND, and silently. A row the caller cannot read was
        skipped with no error and no log: an attachment whose ``res_model``
        names a model no longer in the registry (a common leftover of an
        uninstalled module) is unreadable by every non-superuser INCLUDING an
        administrator, so it stayed behind on the old backend and re-running the
        action never moved it. An operator has no way to see the difference
        between "all migrated" and "all I was allowed to see migrated".

        :meth:`_check_admin_action` is what gates the action; escalating after
        it also drops the per-batch access scan the non-sudo search paid over
        the whole attachment table.
        """
        self._check_admin_action()

        self.sudo().with_context(skip_res_field_check=True).search(
            Domain.AND([self._get_storage_domain(), [("type", "=", "binary")]])
        )._migrate()

    @api.model
    def _full_path(self, path: str) -> str:
        """Return the absolute filestore path of the store key *path*.

        ``resolve()`` is deliberately per-call and NOT cached: it is what makes
        a symlink planted under the filestore resolve to its target, so the
        confinement check below refuses it instead of serving whatever it points
        at. Dropping it for the lexical check alone runs ~3x faster and is just
        as safe against a path that tries to escape by spelling — but a link at
        a shard path stops being refused and starts being read, which is a
        filesystem-trust decision rather than a speed one.

        Fixed subdirectories do not need any of this and go through
        :func:`_resolve_filestore_dir` instead.

        :raise ValueError: if *path* escapes the filestore
        """
        path = self._sanitize_store_path(path)
        filestore = _resolve_filestore_root(self._filestore())
        full = (filestore / path).resolve()
        if not full.is_relative_to(filestore):
            raise ValueError(f"Attachment path {path!r} escapes the filestore")
        return str(full)

    @api.model
    def _filestore_dir(self, name: str) -> Path:
        """Return a fixed filestore subdirectory (``tmp``, ``checklist``)."""
        return _resolve_filestore_dir(self._filestore(), name)

    @api.model
    def _get_image_autoresize_config(self) -> tuple[list[str], int, int, int]:
        """Parse the image-autoresize system parameters, with guards.

        Misconfigured parameters must never crash an upload: an invalid
        resolution disables the resize, an invalid quality falls back to 80.

        :return: ``(subtypes, max_width, max_height, jpeg_quality)``;
            ``max_width``/``max_height`` are 0 when autoresize is disabled
        """
        ICP = self.env["ir.config_parameter"].sudo().get_param
        subtypes = [
            subtype.strip()
            for subtype in ICP(
                "base.image_autoresize_extensions", "png,jpeg,bmp,tiff"
            ).split(",")
        ]
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
        return self._unsized().raw or None

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
        if checksum is None:
            checksum = self._content_checksum(data)
        index_content = self._extract_index_content(data, mimetype, checksum=checksum)
        if backend is None:
            backend = self._storage_backend()
        return {
            "file_size": len(data),
            "checksum": checksum,
            "index_content": index_content,
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
        raw = attach._unsized().raw
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
        super(IrAttachment, attach.sudo()).write(values)
        attach.flush_recordset(
            ["store_fname", "db_datas", "checksum", "file_size", "index_content"]
        )
        if old_fname:
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
        """Move each row's content into the configured backend, bytes unchanged.

        Only the storage location moves, so the derived columns are re-derived
        only when the row has none to trust — a missing ``checksum``, or a
        ``file_size`` the content disagrees with. A row whose metadata is sound
        keeps its ``index_content``: recomputing it would re-run
        :meth:`_index`, which an override (``attachment_indexation``) turns into
        a full PDF/OOXML parse, for bytes that did not change.

        The checksum is the one derived column that can be sound and still
        unusable AS A KEY: :meth:`_is_current_digest` says whether it came from
        the digest store keys are tagged with, and only that decides whether it
        is reused or recomputed.
        """
        record_count = len(self)
        backend = self._storage_backend()
        storage = self._storage().upper()
        _logger.info("Migrating %d attachments to %s", record_count, storage)
        can_commit = not (modules.module.current_test or config["test_enable"])
        for index, attach, raw in self._rewritable_rows(self, "migration"):
            if index % 100 == 0 or index == record_count:
                _logger.info(
                    "Migrating attachment %d/%d to %s", index, record_count, storage
                )
            if bool(attach.checksum) and attach.file_size == len(raw):
                checksum = (
                    attach.checksum
                    if self._is_current_digest(attach.checksum)
                    else self._content_checksum(raw)
                )
                values = {**backend.write(raw, checksum), "checksum": checksum}
            else:
                values = self._get_datas_related_values(raw, attach.mimetype, backend)
            self._rewrite_stored_content(attach, values, attach.store_fname)
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
                raw = self._decode_datas(values["datas"])
            if raw:
                mimetype = guess_mimetype(raw)
        return (mimetype and mimetype.lower()) or "application/octet-stream"

    def _mimetype_for_write(self, vals: dict[str, Any]) -> str:
        """Return the mimetype a content ``write`` must store.

        :meth:`_mimetype_from_values` answers from an explicit ``mimetype``,
        then the filename, then the ``url``, and only sniffs the bytes when none
        of them does. ``create`` hands it the whole row, so ``sheet.xlsx`` keeps
        its OOXML mimetype; ``write`` hands it only the keys being changed, so
        replacing that row's content re-sniffed the bytes and stored
        ``application/zip`` instead — the same file typed differently depending
        on which call last wrote it, and served to the browser as a zip.
        ``report.csv`` flipped between ``text/csv`` and ``text/plain`` with the
        column count. Completing the values from the records themselves is what
        makes a content ``write`` agree with the ``create`` of the same file.

        A key the records disagree on is left out: one ``write`` stores one
        mimetype, so a recordset of differently-named rows has no single
        filename to derive it from and falls back to sniffing, as before.
        """
        naming = {}
        for key in ("name", "url"):
            if key in vals:
                continue
            values = {record[key] for record in self}
            if len(values) == 1 and (value := values.pop()):
                naming[key] = value
        return self._mimetype_from_values(naming | vals)

    def _read_prefix(self, size: int | None = None) -> bytes:
        """Return up to *size* bytes of this attachment's content (all if ``None``).

        The single partial-read primitive. It resolves the three content
        locations — keyed backend, inline ``db_datas``, addon-static ``url`` —
        without materializing more than *size* bytes.
        :class:`~odoo.http.Stream` cannot express a partial read, so callers
        needing only a head (text thumbnails, sniffers) used to re-implement
        this triage against ``store_fname``/``db_datas``/``url`` themselves.

        ``bin_size`` is neutralized by :meth:`_stored_content` (:meth:`_unsized`).

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

    def _unsized(self) -> Self:
        """Return this recordset with every ``bin_size`` flag cleared.

        Under ``bin_size`` a binary field does not read back as its content:
        a stored column becomes ``pg_size_pretty(length(...))`` and a computed
        one with a ``bin_size_field`` becomes ``human_size(...)`` of it — so
        ``raw``/``datas``/``db_datas`` all yield a human size string
        (``b"1.5 kB"``) that is indistinguishable from content to the caller.
        That is a presentation mode for a client read; NOTHING in the content
        pipeline may observe it.

        It used to be neutralized reader by reader, and the readers that were
        missed did not fail — they silently substituted the size string for the
        payload. A content ``write`` under ``bin_size`` blanked the row (the
        inverse reads ``raw`` back, and its value was cached under the
        ``bin_size`` the ORM had stripped, so the read missed and came back
        empty); ``copy`` of a db-stored row, ``_migrate``/``force_storage`` and
        :meth:`_gc_rehash_legacy_keys` each stored ``b"4.90 Kb"`` as the
        content of every row they touched. Those are whole-table sweeps, and
        nothing downstream can tell the result from a legitimately tiny file
        (IRA-Z1).

        Both axes must be cleared: ``bin_size`` alone keys the ORM cache, while
        ``bin_size_<field>`` is read straight from the context by
        ``Binary.compute_value`` without taking part in that key.
        """
        if not any(self.env.context.get(key) for key in BIN_SIZE_KEYS):
            return self
        return self.with_context(**BIN_SIZE_KEYS)

    def _stored_content(self, size: int | None = None) -> bytes | None:
        """Return up to *size* bytes of the content THIS row stores itself.

        The keyed-backend / inline-``db_datas`` triage, shared by
        :meth:`_compute_raw` and :meth:`_read_prefix` — which differ only in what
        they do when there is nothing stored, so that decision is left to them.
        :meth:`_to_http_stream` runs the same triage a third time, in terms of
        streams rather than bytes.

        :param size: maximum number of bytes to read; ``None`` reads it all
        :return: the content, or ``None`` when this row stores none (no store
            key and no inline data)
        """
        self.ensure_one()
        if self.store_fname:
            data = self._backend_for_key(self.store_fname).read(self.store_fname, size)
            self._content_read_back_failed(
                data, self.file_size, self.id, self.store_fname, "serving empty bytes"
            )
            return data
        if db_datas := self._unsized().db_datas:
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

    @api.model
    def _is_canonical_store_key(self, fname: str) -> bool:
        """Whether *fname* survives :meth:`_sanitize_store_path` unchanged.

        The GC recovers a store key from the NAME of its checklist marker, then
        addresses two different things with it: the ``store_fname`` column (to
        learn whether any row still references the content) and, through
        :meth:`_full_path`, the file to unlink. Sanitizing happens only on the
        second, so for any name it rewrites the two stop being the same file —
        the GC would ask about ``ab/cd.ef`` and delete ``ab/cdef``, which no
        checklist entry ever named and which may be live content.

        Every key :meth:`_file_store_path` produces is hex and ``/``, hence
        already canonical, so this rejects nothing the filestore wrote. What it
        rejects is a stray file dropped under ``checklist/`` by something else —
        an editor swap file, an NFS silly-rename (``.nfs0000...``), a backup
        tool — which is exactly the case where the two addresses diverge
        (IRA-G3).

        A rejected entry is DELETED rather than left alone: it can never match a
        ``store_fname``, so skipping it would pin it in the checklist forever,
        where it still counts against :attr:`_GC_MAX_ENTRIES` and can eventually
        crowd out real markers. Deleting the marker is what the sweep did before
        the guard; the guard only stops it from also unlinking a filestore path
        that no marker named.
        """
        return bool(fname) and self._sanitize_store_path(fname) == fname

    def _set_attachment_data(self, asbytes: Callable[[Any], bytes]) -> None:
        """Store new content for each row and release the keys it replaces.

        Replacing content releases old keys through the same batched path
        ``unlink`` uses. Going one key at a time re-entered
        :meth:`_mark_for_gc_multi` per row, re-deriving the checklist directory
        and re-creating the shard directory for each — the batching that method
        exists for was unreachable from the write side, which is the side that
        runs on every content replacement.
        """
        self._check_serving_attachments()
        old_fnames = []
        wrote_content = False
        backend = self._storage_backend()
        memo_key: tuple[bytes, str] | None = None
        memo_vals: dict[str, Any] = {}

        for attach in self._unsized():
            bin_data = asbytes(attach)
            if memo_key and memo_key[0] is bin_data and memo_key[1] == attach.mimetype:
                vals = memo_vals
            else:
                vals = self._get_datas_related_values(
                    bin_data, attach.mimetype, backend
                )
                memo_key, memo_vals = (bin_data, attach.mimetype), vals

            if attach.store_fname:
                old_fnames.append(attach.store_fname)

            super(IrAttachment, attach.sudo()).write(vals)

            if bin_data:
                wrote_content = True

        if old_fnames or wrote_content:
            self.flush_recordset(["checksum", "store_fname"])
        self._storage_delete_multi(OrderedSet(old_fnames))

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
            image_data = img.image_quality(quality=quality if subtype == "jpeg" else 0)
            if is_raw:
                values["raw"] = image_data
            else:
                values["datas"] = base64.b64encode(image_data)
        except (UserError, OSError, image.Image.DecompressionBombError) as e:
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
        if file_type and file_type.startswith("text/"):
            text = bin_data[: self._INDEX_MAX_BYTES].decode("utf-8", errors="ignore")
            words = re.findall(r"[^\x00-\x1f\x7f-\x9f]{4,}", text)
            return "\n".join(words)
        return None

    @api.model
    def _extract_index_content(
        self, bin_data: bytes, mimetype: str, checksum: str | None = None
    ) -> str | None:
        """Return the ``index_content`` to persist for *bin_data*, bounded.

        The single point where an extraction becomes a stored column, so the
        bound applies to whatever any override produced —
        ``attachment_indexation`` returns its PDF/OOXML text without calling
        ``super()``, so capping inside :meth:`_index` would have covered only
        the base implementation.

        A cap is needed because ``_INDEX_MAX_BYTES`` caps the bytes fed IN, and
        for text the extraction is near-identity: a 4 MiB text upload stored
        4,180,159 characters in Postgres beside the 4 MiB already in the
        filestore, doubling the cost of every log, CSV and dump attached. The
        column is really indexed — ``hr_recruitment`` builds a trigram index
        over it — and a GIN entry per multi-megabyte document is what makes that
        expensive, not the row count.

        The cut is on characters, at ``ir_attachment.index_max_chars``; set it
        to ``0`` to index whole documents as before. Truncation costs matches
        past the cap, so the default is set well above ordinary documents.
        """
        index_content = self._index(bin_data, mimetype, checksum=checksum)
        if not index_content:
            return index_content
        limit = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("ir_attachment.index_max_chars", self._INDEX_MAX_CHARS)
        )
        if limit <= 0 or len(index_content) <= limit:
            return index_content
        _logger.debug(
            "index_content truncated from %d to %d characters",
            len(index_content),
            limit,
        )
        return index_content[:limit]

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

    @api.model
    def _as_model_name(self, res_model: Any) -> str | None:
        """Return *res_model* if it can name a model, else ``None``.

        ``res_model`` arrives straight from ``create``/``write`` values, i.e.
        from RPC, before the ORM has converted anything. Every consumer here
        treats it as a hashable string — a dict key in :meth:`create` and
        :meth:`write`, a registry lookup in :meth:`_check_res_field_valid` — so
        a client passing a list turned an access check into
        ``TypeError: cannot use 'list' as a dict key``, a 500 out of a security
        gate rather than a refusal. A non-string is not a model, so it resolves
        to no comodel and is refused by the same path that refuses an unknown
        one.
        """
        return res_model if isinstance(res_model, str) and res_model else None

    def _inaccessible_comodel_records(
        self, model_and_ids: dict[Any, Collection[int]], operation: str
    ) -> Generator[tuple[str, int]]:
        if self.env.su:
            return
        for res_model, res_ids in model_and_ids.items():
            res_ids = OrderedSet(filter(None, res_ids))
            if not res_model or not res_ids:
                continue
            if res_model not in self.env:
                for res_id in res_ids:
                    yield res_model, res_id
                continue
            if res_model == "res.users" and self.env.uid in res_ids:
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
    def _scan_prefilter(self, sec_domain: Domain) -> Domain:
        """Return the SQL condition narrowing what the access scan has to read.

        The scan (:meth:`_fetch_accessible_ids`) is the authority: it fetches
        rows and asks :meth:`_check_access` about each, so its cost is set by
        how many rows SQL hands it — and ``res_model != False`` excludes nothing
        on a table whose rows are almost all linked. An unbounded scan is
        therefore linear in the TABLE, not in the result (measured 10.7 / 21.0 /
        43.8 / 83.5 ms at 2.5k / 5k / 10k / 20k rows).

        What is cheap to exclude in SQL is a model the user cannot read AT ALL:
        :meth:`_check_access` refuses every attachment linked to one, and the
        answer is a model-level ACL lookup that is already ormcached, so the
        whole term is a ``res_model NOT IN (...)`` list with no subquery and no
        planning cost. Portal and low-privilege users — the ones whose scans are
        worst, because almost nothing they touch is accessible — are exactly the
        ones this prunes for.

        Per-RECORD exclusion is deliberately NOT done here. The obvious
        extension is to OR in :meth:`_search_models_security_domain`'s
        per-comodel subqueries, and it was measured to be a net LOSS: an
        unrestricted comodel contributes a subquery that excludes nothing, so a
        bounded search went from 5.5 ms to 13.9 ms and an unbounded count from
        92 ms to 112 ms, buying a 2.8x win only when the accessible set happens
        to be sparse — which cannot be known without doing the work. The domain
        naming its models keeps taking that path (``_SEARCH_MODEL_DOMAIN_LIMIT``)
        because there the planner can use ``res_model`` to cut the scan first.

        This is a PREFILTER, not a path switch: the post-filter stays the
        authority, so letting too much through only costs time. It must never
        DROP a row the authority would allow, hence the trailing ``not in``
        shape — anything the discovery did not report, ``res_model``-less rows
        included, passes through untouched.
        """
        model_names, capped = self._attached_model_names()
        if capped:
            return sec_domain | Domain("res_model", "!=", False)
        unreadable = [
            name
            for name in model_names
            if (comodel := self.env.get(name)) is not None
            and not comodel.has_access("read")
        ]
        if not unreadable:
            return sec_domain | Domain("res_model", "!=", False)
        return sec_domain | Domain("res_model", "not in", unreadable)

    @api.model
    @ormcache()
    def _attached_model_names(self) -> tuple[list[str], bool]:
        """Return ``(model names, capped)`` for the whole table.

        The distinct ``res_model`` values, read straight from SQL and cached per
        registry. Three deliberate choices, all of which the ``not in`` shape of
        :meth:`_scan_prefilter` is what makes affordable:

        * **not per domain.** Grouping under the caller's domain would name
          fewer models, but it has to run inside :meth:`_search` — which is
          re-entered from ``fetch()`` while a field read is in flight, and
          issuing a grouped ORM read there blows up in the cache layer.
        * **cached, and never invalidated on write.** A model whose first
          attachment appears after the cache was filled is simply not pruned
          until the next registry cache clear, which is what happens today for
          every model anyway. Correctness does not depend on freshness, so it
          buys the one full pass this needs (1.9 ms over 20k rows; 0.3 us
          cached).
        * **raw SQL**, one grouped index-only scan of ``_res_field_idx``'s
          leading column, returning plain values.

        *capped* reports more distinct models than the prefilter is willing to
        enumerate, one past the limit being enough to know.
        """
        limit = self._SEARCH_MODEL_DISCOVERY_LIMIT + 1
        self.env.cr.execute(
            "SELECT res_model FROM ir_attachment GROUP BY res_model LIMIT %s",
            [limit],
        )
        rows = [row[0] for row in self.env.cr.fetchall()]
        return sorted(name for name in rows if name), len(rows) >= limit

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
        non-system user, when ``res_field`` names a readable field. Only the
        small-model path uses this (``len <= _SEARCH_MODEL_DOMAIN_LIMIT``); the
        rest go through :meth:`_fetch_accessible_ids`. Both must agree with
        :meth:`_check_access`, the authority — this domain is the ONLY filter on
        its path, with no post-filter to catch what it lets through (IRA-B6).

        Three ways this used to disagree with it:

        * the field clause listed only binary fields and relations to
          ``ir.attachment``, where :meth:`_check_access` accepts ANY field the
          user can read. Every ``res_field`` written in this codebase names a
          binary field, so the narrower list is right about the data — but it is
          not the authority, and being right about the data is not the same as
          agreeing with it. One row with a ``res_field`` naming an ordinary
          readable field was returned by a six-model search and dropped by the
          one-model search of the same rows: the result of ``search`` depended
          on how many models the domain happened to name (IRA-D5). Fail-closed,
          so nothing leaked — but the two paths must not answer differently;

        * a comodel the user cannot read at all made ``_search`` RAISE, so
          searching one's own attachments failed with an ``AccessError`` naming
          an unrelated model — while the same search over six models quietly
          returned nothing for it. Unreachable is not an error here: the model
          contributes no subdomain, exactly as :meth:`_check_access` treats it;
        * an unrestricted comodel query (no record rule, no ``res_id``
          condition) skipped the ``res_id`` clause as a tautology. It is not
          one: ``res_id IN (SELECT id FROM comodel)`` still excludes NULL and
          ``0``, and those rows are the unlinked ones
          :meth:`_check_access` reserves for their creator. Any user could read
          another's ``res_model``-set, ``res_id``-less attachment — content
          included — as soon as the comodel carried no rule (the common case
          for master data). ``res_id != False`` restores the bound without
          paying for the subquery.

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
                    lambda cond, codomain=codomain: (
                        codomain & cond if cond.field_expr == "res_model" else cond
                    )
                ),
            )
            try:
                query = comodel._search(
                    Domain("id", "in", comodel_res_ids)
                    if comodel_res_ids
                    else Domain.TRUE
                )
            except AccessError:
                continue
            if query.is_empty():
                continue
            codomain &= (
                Domain("res_id", "in", query)
                if query.where_clause
                else Domain("res_id", "!=", False)
            )
            if not disable_binary_fields_attachments and not self.env.is_system():
                accessible_fields = [
                    field.name
                    for field in comodel._fields.values()
                    if comodel._has_field_access(field, "read")
                ]
                accessible_fields.append(False)
                codomain &= Domain("res_field", "in", accessible_fields)
            models_domain |= codomain
        return models_domain

    @api.model
    def _accessible_batch_seek(
        self, order: str | None, bound: int | None
    ) -> tuple[str, Callable[[Self], Domain] | None]:
        """Return the ``(order, keyset)`` pair driving the batched access scan.

        *keyset* builds the domain seeking past the last row of a batch, so
        every batch costs what the first one did. ``None`` falls back to OFFSET,
        which re-scans each skipped row and makes the whole scan quadratic
        (IRA-B5).

        A caller ``order`` is made total by appending the unique ``id``, else
        ties across a batch boundary could be skipped or duplicated — an
        access-control hazard, not just a perf one. It also yields a keyset
        whenever its LEADING term is ``id``, which is what makes the fast path
        reachable at all: ``search_fetch`` substitutes ``_order`` (``id desc``)
        for a missing order, so ``_search`` sees an explicit order on every
        ordinary ``search()`` and the keyset branch below would otherwise only
        ever run for ``search_count`` and subqueries — the exact order it would
        have picked for itself, taken as a reason not to use it.

        Any other leading term keeps OFFSET on purpose: a keyset over it must
        reproduce that column's NULL placement and collation exactly, and
        getting that wrong silently drops rows instead of merely being slow.
        """
        if order:
            column, _, direction = order.split(",")[0].strip().partition(" ")
            if column != "id":
                return f"{order}, id", None
            operator = ">" if not direction.strip().lower().startswith("desc") else "<"
            return order, lambda last: Domain("id", operator, last.id)

        if bound is None:
            return "id desc", lambda last: Domain("id", "<", last.id)

        def by_res_model(last: Self) -> Domain:
            if last.res_model:
                return (
                    Domain("res_model", "=", last.res_model)
                    & Domain("id", ">", last.id)
                ) | Domain("res_model", ">", last.res_model)
            return (
                Domain("res_model", "=", False) & Domain("id", ">", last.id)
            ) | Domain("res_model", "!=", False)

        return "res_model nulls first, id", by_res_model

    def _fetch_accessible_ids(
        self, domain: Domain, order: str | None, bound: int | None
    ) -> list[int]:
        """Collect ids readable by the current user, fetching by batches.

        Batches advance by keyset pagination whenever
        :meth:`_accessible_batch_seek` can derive a seek predicate for the
        effective order, and by OFFSET otherwise.

        A batch's ``SECURITY_FIELDS`` are dropped from the ORM cache once
        ANOTHER batch is known to follow. Batching bounded the QUERY size but
        nothing bounded the cache: the five fields of every row ever examined
        stayed resident for the rest of the request, so an unbounded scan cost
        O(accessible rows) of memory to produce a list of ints — 23 MB to count
        50k attachments, and the count is the one caller that never passes a
        bound (P2-9). Only the ids leave this method, and :meth:`_check_access`
        already invalidates the rows it refuses.

        The LAST batch is deliberately left cached, because it is the one a
        caller reads next: every bounded search the web client issues fits in
        one batch, and invalidating it made ``search(limit=80)`` followed by a
        read of ``res_model`` re-fetch rows it had just loaded. Keeping it costs
        one batch of memory — the bound this method exists to establish.

        :param bound: stop once this many ids are collected (None: collect all)
        :return: the accessible ids
        """
        order, keyset = self._accessible_batch_seek(order, bound)

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
                break
            if bound is not None and len(result) >= bound:
                break
            if keyset is not None:
                batch_domain = domain & keyset(records.sudo()[-1])
            else:
                sub_offset += PREFETCH_MAX
            records.invalidate_recordset(SECURITY_FIELDS)
        return result

    def _post_add_create(self, **kwargs: Any) -> None:
        """Hook called after an attachment is uploaded. Overridden by mail, account, etc."""

    def generate_access_token(self) -> list[str]:
        tokens = []
        new_tokens = {}
        for attachment in self:
            if attachment.access_token:
                tokens.append(attachment.access_token)
                continue
            token = self._generate_access_token()
            new_tokens[attachment.id] = token
            tokens.append(token)
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

        Field-backing rows (``res_field`` set) take no part in dedup, on EITHER
        side: they are excluded from the match set, and a value that asks for
        one is always given a row of its own. Only the first half was enforced,
        and the other two directions were each wrong in their own way. A value
        carrying ``res_field`` matched a free-standing row and was handed its id
        — so the caller asked for "field X of record Y" and got back an
        unrelated attachment, with the field left unbacked and nothing
        indicating it. And within one batch a ``res_field`` value could register
        the key first, handing the NEXT, free-standing value a field-backing id:
        the guard below, arrived at from the other end.

        The id returned here is one the CALLER keeps — it puts it in a message body,
        a ``/web/image/<id>`` url, a relation. A ``res_field`` row is not free
        to be kept that way: it IS field X of record Y, so the ORM rewrites its
        content whenever that field is written
        (:meth:`Binary.mark_dirty` writes ``datas`` onto the existing row),
        deletes it when the field is cleared, and deletes it with the host
        record. Reusing one therefore handed the caller a reference whose bytes
        change and whose lifetime belongs to somebody else — a partner avatar
        update silently swapped the image in an already-sent message, and
        deleting the partner deleted it (IRA-C4). Dedup is an optimization; it
        may only ever reuse a row that stands on its own.

        :raise UserError: if a value is not base64-encoded or omits ``mimetype``

        .. note::
            The dedup search runs as ``sudo()`` to match a filestore-shared file
            across companies, so the returned id may belong to another company.
            Reading it is still ACL-gated, so no content leaks (IRA-C2).
        """
        entries: list[tuple[dict, tuple[str, int, str] | None]] = []
        raw_by_key: dict[tuple, bytes] = {}
        for values in values_list:
            if "mimetype" not in values:
                raise UserError(_("Attachment is missing its mimetype."))
            vals = dict(values)
            has_content = self._normalize_content_vals(vals)
            vals = self._check_contents(vals)
            key = None
            if has_content:
                raw = vals["raw"]
                key = (self._content_checksum(raw), len(raw), vals["mimetype"])
                raw_by_key.setdefault(key, raw)
            entries.append((vals, key))

        all_checksums = list({key[0] for _vals, key in entries if key})
        existing_by_key: dict[tuple, int] = {}
        if all_checksums:
            for checksum, file_size, mimetype, att_id in self.sudo()._read_group(
                [("checksum", "in", all_checksums), ("res_field", "=", False)],
                groupby=["checksum", "file_size", "mimetype"],
                aggregates=["id:max"],
            ):
                existing_by_key[checksum, file_size, mimetype] = att_id
        self._drop_colliding_dedup_matches(existing_by_key, raw_by_key)

        to_create = []
        new_index_by_key: dict[tuple, int] = {}
        own_indexes: list[int | None] = []
        for vals, key in entries:
            if key is None or vals.get("res_field"):
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

    def _drop_colliding_dedup_matches(
        self, existing_by_key: dict[tuple, int], raw_by_key: dict[tuple, bytes]
    ) -> None:
        """Discard :meth:`create_unique` matches whose stored bytes differ.

        Content is deduplicated in two places, and until now only one of them
        honoured :meth:`_verify_content_collision`. :meth:`_get_path` re-reads
        the stored file before letting new content share a filestore key,
        because a digest with practical collisions otherwise makes one upload
        serve another's bytes. :meth:`create_unique` reuses a whole ROW on a
        ``(checksum, file_size, mimetype)`` match and never reached that check —
        a dedup hit returns the existing id and the caller's payload is dropped,
        unread. Uploading a file that collides with a stored one therefore
        returned a row serving the OTHER file, with the mitigation enabled and
        silent.

        Verifying here costs one content read per distinct match, and only when
        the operator (or the sha1 default) asks for it. A match that fails goes
        back through :meth:`create`, whose write raises the usual collision
        ``UserError`` rather than substituting content.
        """
        if not existing_by_key or not self._verify_content_collision():
            return
        for key, att_id in list(existing_by_key.items()):
            if self.browse(att_id).sudo()._stored_content() != raw_by_key.get(key):
                del existing_by_key[key]
                _logger.warning(
                    "create_unique: attachment %s shares the digest of new "
                    "content but not its bytes; not reusing it",
                    att_id,
                )

    def _generate_access_token(self) -> str:
        return str(uuid.uuid4())

    @api.model
    def action_get(self) -> dict[str, Any]:
        return self.env["ir.actions.act_window"]._for_xml_id("base.action_attachment")

    def _from_request_file(
        self, file: Any, *, mimetype: str = "DERIVE", **vals: Any
    ) -> Self:
        """Create an attachment out of a request file.

        THE upload entry point, and the only one that can stream: it decides
        per mimetype whether the payload has to be buffered (see
        :meth:`_should_stream_upload`) and otherwise hands the file object to
        :meth:`_create_from_stream`, whose peak memory is one chunk. Uploading
        through ``create({"raw": file.read()})`` instead — which is what the
        chatter and the backend uploader did — holds the whole file in the
        worker, twice over once the ORM has a copy.

        :param file: the request file
        :param str mimetype: one of —

            * ``"DERIVE"`` (default) — type it exactly as ``create`` would from
              the same filename: the extension first, the content only if that
              says nothing. The filename is kept as sent. This is the mode for
              an upload with no policy of its own, and the only one that leaves
              the resulting row indistinguishable from the buffered ``create``
              it replaces;
            * ``"TRUST"`` — use the request file's mimetype/extension unverified;
            * ``"GUESS"`` — detect from content, appending the extension unless
              the filename already has a valid one;
            * ``"{type}/{subtype}"`` — force this mimetype, appending its
              extension unless the filename already has a valid one.

        ``DERIVE`` sniffs at most :data:`MIMETYPE_HEAD_SIZE` bytes where the
        buffered path sniffed the whole payload. That only differs for a file
        whose extension says nothing AND whose type needs more than the head to
        recognise; anything named ``*.xlsx`` or ``*.csv`` is typed from the name
        and never read.
        """
        if mimetype == "DERIVE":
            filename = file.filename
            mimetype = mimetypes.guess_type(filename or "")[0] or ""
            if not mimetype or mimetype == "application/octet-stream":
                head = file.read(MIMETYPE_HEAD_SIZE)
                file.seek(-len(head), 1)
                mimetype = guess_mimetype(head)
        elif mimetype == "TRUST":
            mimetype = file.content_type
            filename = file.filename
        elif mimetype == "GUESS":
            head = file.read(MIMETYPE_HEAD_SIZE)
            file.seek(-len(head), 1)
            mimetype = guess_mimetype(head)
            filename = fix_filename_extension(file.filename, mimetype)
            if mimetype in ("application/zip", *_olecf_mimetypes):
                mimetype = mimetypes.guess_type(filename)[0] or mimetype
        elif "/" in mimetype and all(mimetype.split("/", 1)):
            filename = fix_filename_extension(file.filename, mimetype)
        else:
            raise ValueError(f"{mimetype=}")

        if self._should_stream_upload(mimetype):
            return self._create_from_stream(
                file, name=filename, mimetype=mimetype, **vals
            )
        return self.create(
            {
                "name": filename,
                "type": "binary",
                "raw": file.read(),
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
        store_values = self._storage_backend().write_stream(fileobj)
        read_size = self._index_read_size(record.mimetype)
        index_content = None
        if read_size != 0:
            content = b""
            readable = True
            if store_values.get("store_fname"):
                content = self._backend_for_key(store_values["store_fname"]).read(
                    store_values["store_fname"], read_size
                )
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
                index_content = self._extract_index_content(
                    content, record.mimetype, checksum=store_values.get("checksum")
                )
        store_values["index_content"] = index_content
        super(IrAttachment, record.sudo()).write(store_values)
        record._check_serving_attachments()
        return record

    def _to_http_stream(self) -> Stream:
        """Create a :class:`~Stream` from an ir.attachment record.

        The keyed / inline / addon-static triage of :meth:`_stored_content`,
        expressed in streams rather than bytes. ``bin_size`` is neutralized on
        the inline leg (:meth:`_unsized`) for the same reason it is everywhere
        else: under it a stored binary column reads back as its own
        human-readable size, so this served ``b"4.88 Kb"`` as the response body
        of a 5000-byte attachment.
        """
        self.ensure_one()

        stream = Stream(
            mimetype=self.mimetype,
            download_name=self.name,
            etag=self.checksum,
            public=self.public,
        )

        if self.store_fname:
            return self._backend_for_key(self.store_fname).to_stream(self, stream)

        inline = self._unsized().db_datas
        if inline:
            stream.type = "data"
            stream.data = inline
            stream.last_modified = self.write_date
            stream.size = len(inline)

        elif self.url:
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

    @api.autovacuum
    def _audit_url_attachments(self) -> None:
        """Defense-in-depth observation for ``ir.http._serve_fallback``.

        That fallback resolves a request path to a ``type='binary'`` attachment
        with a matching ``url`` and serves it under ``sudo()``. It restricts
        itself to ``public=True`` rows, so a ``url``-set, ``public=False`` row is
        not served — it is an oddity suggesting a misconfiguration or a
        controller leaking input into ``vals``, and it will 404 where its author
        expected content. Overrides of ``_get_serve_attachment`` supply their own
        ``extra_domain`` (``website`` does) and are not bound by that
        restriction, which is what keeps this worth watching.
        ``_check_serving_attachments`` blocks non-admin writes; this catches what
        slips through ``sudo()`` bypasses. An observation, not a block.

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
        skipped = False
        for backend_cls in tuple(STORAGE_BACKENDS.values()):
            if backend_cls(self.env).autovacuum() is False:
                skipped = True
        return False if skipped else None

    @api.model
    def _legacy_key_domain(self) -> Domain:
        """Return the domain matching rows NOT stored under a current store key.

        The pattern comes from :meth:`_file_store_path` itself, fed a digest of
        underscores: LIKE reads each ``_`` as "any one character", so what the
        writer produces IS the shape the reader matches, and a change of layout
        cannot leave the two out of step. Digests being fixed-width hex is what
        makes that trick exact.

        Matching the whole SHAPE and not just the ``<algo>/`` prefix is what
        catches a key that carries the current tag over a foreign digest — see
        :meth:`_is_current_digest`. Keys owned by another backend (``s3://``)
        are excluded: they are not this pass's to re-key.
        """
        return Domain(
            [
                ("store_fname", "!=", False),
                (
                    "store_fname",
                    "not =like",
                    self._file_store_path("_" * CONTENT_DIGEST_LEN),
                ),
                ("store_fname", "not like", "://"),
            ]
        )

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

        :meth:`_legacy_key_domain` selects the batch by the SHAPE of a current
        key rather than by its ``<algo>/`` prefix, so this also repairs the
        tag-over-foreign-digest keys an earlier :meth:`_migrate` wrote (see
        :meth:`_is_current_digest`) instead of skipping them as converged.

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
        re-reading the same broken rows. Those wait for the next run. It is
        counted only up to one batch past *limit*, since all the contract asks
        is whether there is more to do — an exact count means a sequential scan
        over every attachment (the domain is a negated LIKE) on each run, paid
        to print a number nobody acts on.

        :param limit: rows to re-key this run; defaults to the parameter
        :return: ``(re-keyed, remaining)`` — the autovacuum re-queue contract
        """
        if ALGO_TAG == "s1":
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
            return 0, 0

        domain = self._legacy_key_domain()
        model = self.sudo().with_context(skip_res_field_check=True)
        legacy = model.search(domain, order="id", limit=limit)
        rekeyed = 0
        backend = self._storage_backend()
        for _index, attach, raw in self._rewritable_rows(legacy, "rehash"):
            checksum = self._content_checksum(raw)
            self._rewrite_stored_content(
                attach,
                {**backend.write(raw, checksum), "checksum": checksum},
                attach.store_fname,
            )
            rekeyed += 1
        if not rekeyed:
            return 0, 0
        remaining = model.search_count(domain, limit=limit + 1)
        _logger.info(
            "filestore rehash: re-keyed %d attachment(s) to the %s digest "
            "(%s%d still on a legacy key)",
            rekeyed,
            ALGO_TAG,
            "at least " if remaining > limit else "",
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
        tmp_dir = self._filestore_dir("tmp")
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
        checklist_root = self._filestore_dir("checklist")
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
                        skipped += 1
                        continue
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
        """Unlink the content of every checklist entry no row still references.

        An entry the filestore cannot address is DROPPED, never raised on. There
        are two such shapes and they used to be handled inconsistently: a
        non-canonical name (:meth:`_is_canonical_store_key`) was dropped, while a
        canonical name whose shard resolves out of the filestore — a symlink
        planted under it, which :meth:`_full_path` refuses precisely so it is
        never read — escaped as a ``ValueError`` out of the whole sweep.

        That turned the confinement check into a permanent denial of the GC: the
        sweep aborts on the first such entry, every later entry in the walk is
        left unswept, the enclosing autovacuum rolls back and drops the table
        lock, and the next run walks the same directory and stops in the same
        place. One planted link stranded 213 of 304 markers here, with the
        filestore growing unbounded behind them.

        Dropping the marker is right for the same reason it is for a
        non-canonical name: a key the filestore refuses can address neither the
        file to unlink nor a live ``store_fname`` (:meth:`_file_read` refuses it
        too), so keeping the entry reclaims nothing and pins it against
        :attr:`_GC_MAX_ENTRIES` forever. It is logged at WARNING rather than
        INFO because, unlike a stray editor file, it means something put a link
        inside the filestore.
        """
        if checklist is None:
            checklist = self._gc_checklist()
        if grace is None:
            grace = self._GC_CHECKLIST_GRACE

        removed = 0
        for names in batched(checklist, self.env.cr.BATCH_SIZE, strict=False):
            self.env.cr.execute(
                "SELECT store_fname FROM ir_attachment WHERE store_fname = ANY(%s)",
                [list(names)],
            )
            whitelist = {row[0] for row in self.env.cr.fetchall()}

            for fname in names:
                filepath = checklist[fname]
                if not self._is_canonical_store_key(fname):
                    _logger.info(
                        "filestore gc: dropping checklist entry %s, whose name is "
                        "not a store key this filestore writes",
                        filepath,
                    )
                    with contextlib.suppress(OSError):
                        Path(filepath).unlink()
                    continue
                if fname not in whitelist:
                    if grace:
                        try:
                            if filepath.stat().st_mtime > time.time() - grace:
                                continue
                        except OSError:
                            pass
                    try:
                        full_path = self._full_path(fname)
                    except ValueError:
                        _logger.warning(
                            "filestore gc: dropping checklist entry %s, whose "
                            "store key resolves outside the filestore",
                            filepath,
                        )
                        with contextlib.suppress(OSError):
                            Path(filepath).unlink()
                        continue
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
        checklist_dir = self._filestore_dir("checklist")
        by_shard_dir: dict[Path, list[Path]] = defaultdict(list)
        for fname in fnames:
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

    def _can_return_content(
        self, field_name: str | None = None, access_token: str | None = None
    ) -> bool:
        self.ensure_one()
        attachment_sudo = self.sudo().with_context(prefetch_fields=False)
        if access_token:
            if not consteq(attachment_sudo.access_token or "", access_token):
                msg = "Invalid access token"
                raise AccessError(msg)
            return True
        if attachment_sudo.public:
            return True
        if self.env.user._is_portal():
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
            operation = "write"

        model_ids = defaultdict(set)
        att_model_ids = []
        field_access: dict[tuple[str, str], bool] = {}
        remaining = remaining.sudo()
        remaining.fetch(SECURITY_FIELDS)
        for attachment in remaining:
            if attachment.public and operation == "read":
                continue
            att_id = attachment.id
            res_model, res_id = attachment.res_model, attachment.res_id
            if not self.env.is_system():
                linked = bool(res_model and res_id)
                if not linked and attachment.create_uid.id != self.env.uid:
                    forbidden_ids.add(att_id)
                    continue
                if res_field := attachment.res_field:
                    if res_model not in self.env:
                        forbidden_ids.add(att_id)
                        continue
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
            forbidden.invalidate_recordset(SECURITY_FIELDS)
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
        if self.env.is_admin():
            return
        served = self.filtered(lambda a: a.type == "binary" and a.url)
        if not served:
            return
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
        if mimetype.startswith("application/vnd.openxmlformats"):
            return False
        subtype = mimetype.partition("/")[2]
        return (
            "html" in subtype or subtype in {"hta", "xml"} or subtype.endswith("+xml")
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
