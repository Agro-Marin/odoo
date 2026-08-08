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
    return Path(filestore).resolve()


@functools.cache
def _resolve_filestore_dir(filestore: str, name: str) -> Path:
    return _resolve_filestore_root(filestore) / name


def condition_values(
    model: Any, field_name: str, domain: Domain
) -> Collection[Any] | None:
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
        return field.type == "binary" or (
            field.relational and field.comodel_name == self._name
        )

    def _check_res_field_valid(self, res_model: str, res_field: str) -> None:
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
        try:
            return base64.b64decode(datas or b"")
        except ValueError as exc:
            raise UserError(_("Attachment is not encoded in base64.")) from exc

    def _normalize_content_vals(self, vals: dict[str, Any]) -> bool:
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
                    vals.pop("db_datas", None)
                elif attachment.checksum or attachment.db_datas:
                    vals["raw"] = attachment.raw
        return vals_list

    def copy(self, default: ValuesType | None = None) -> Self:
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
        return backend_for_key(self.env, fname)

    def _content_checksum(self, bin_data: bytes) -> str:
        return content_hash(bin_data or b"")

    @api.model
    def _is_current_digest(self, checksum: str | bool) -> bool:
        return bool(checksum) and len(checksum) == CONTENT_DIGEST_LEN

    @api.model
    def _filestore(self) -> str:
        return config.filestore(self.env.cr.dbname)

    @api.model
    def _file_delete(self, fname: str) -> None:
        self._file_delete_multi((fname,))

    @api.model
    def _file_delete_multi(self, fnames: Collection[str]) -> None:
        self._mark_for_gc_multi(fnames)

    @api.model
    def _file_store_path(self, checksum: str) -> str:
        if ALGO_TAG == "s1":
            return checksum[:2] + "/" + checksum
        return f"{ALGO_TAG}/{checksum[:2]}/{checksum}"

    @api.model
    def _file_read(self, fname: str, size: int | None = None) -> bytes:
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
        if not self.env.is_admin():
            raise AccessError(_("Only administrators can execute this action."))

    @api.model
    def force_storage(self) -> None:
        self._check_admin_action()

        self.sudo().with_context(skip_res_field_check=True).search(
            Domain.AND([self._get_storage_domain(), [("type", "=", "binary")]])
        )._migrate()

    @api.model
    def _full_path(self, path: str) -> str:
        path = self._sanitize_store_path(path)
        filestore = _resolve_filestore_root(self._filestore())
        full = (filestore / path).resolve()
        if not full.is_relative_to(filestore):
            raise ValueError(f"Attachment path {path!r} escapes the filestore")
        return str(full)

    @api.model
    def _filestore_dir(self, name: str) -> Path:
        return _resolve_filestore_dir(self._filestore(), name)

    @api.model
    def _get_image_autoresize_config(self) -> tuple[list[str], int, int, int]:
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
        return self._storage_backend().migration_domain()

    @api.model
    def _get_path(
        self, bin_data: bytes | None, sha: str, *, source_path: str | None = None
    ) -> tuple[str, str]:
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
        return ["base.group_system"]

    def _content_for_rewrite(self, attach: Self, operation: str) -> bytes | None:
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
        super(IrAttachment, attach.sudo()).write(values)
        attach.flush_recordset(
            ["store_fname", "db_datas", "checksum", "file_size", "index_content"]
        )
        if old_fname:
            attach._storage_delete(old_fname)

    def _rewritable_rows(
        self, rows: Self, operation: str
    ) -> Generator[tuple[int, Self, bytes]]:
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
        naming = {}
        for key in ("name", "url"):
            if key in vals:
                continue
            values = {record[key] for record in self}
            if len(values) == 1 and (value := values.pop()):
                naming[key] = value
        return self._mimetype_from_values(naming | vals)

    def _read_prefix(self, size: int | None = None) -> bytes:
        self.ensure_one()
        stored = self._stored_content(size)
        if stored is not None:
            return stored
        if static_path := self._static_file_path():
            with file_open(static_path, "rb") as file:
                return file.read(size)
        return b""

    def _unsized(self) -> Self:
        if not any(self.env.context.get(key) for key in BIN_SIZE_KEYS):
            return self
        return self.with_context(**BIN_SIZE_KEYS)

    def _stored_content(self, size: int | None = None) -> bytes | None:
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
        self.ensure_one()
        if not self.url:
            return None
        host = request.httprequest.environ.get("HTTP_HOST", "") if request else ""
        return root.get_static_file(self.url, host=host)

    @api.model
    def _streams_equal(self, stream_a: Any, stream_b: Any) -> bool:
        while True:
            chunk_a = stream_a.read(self._COMPARE_BLOCK_SIZE)
            if chunk_a != stream_b.read(self._COMPARE_BLOCK_SIZE):
                return False
            if not chunk_a:
                return True

    @api.model
    def _same_as_file(self, source: Any, source_size: int, filepath: str) -> bool:
        if Path(filepath).stat().st_size != source_size:
            return False
        with Path(filepath).open("rb") as fd:
            return self._streams_equal(source, fd)

    @api.model
    def _same_content(self, bin_data: bytes, filepath: str) -> bool:
        with io.BytesIO(bin_data) as buf:
            return self._same_as_file(buf, len(bin_data), filepath)

    @api.model
    def _same_content_files(self, path_a: str, path_b: str) -> bool:
        with Path(path_a).open("rb") as fa:
            return self._same_as_file(fa, Path(path_a).stat().st_size, path_b)

    @api.model
    def _sanitize_store_path(self, path: str) -> str:
        return re.sub(r"[.:]", "", path).strip("/\\")

    @api.model
    def _is_canonical_store_key(self, fname: str) -> bool:
        return bool(fname) and self._sanitize_store_path(fname) == fname

    def _set_attachment_data(self, asbytes: Callable[[Any], bytes]) -> None:
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
        backend_cls = STORAGE_BACKENDS.get(self._storage(), FileStorage)
        return backend_cls(self.env)

    @api.model
    def _storage_delete(self, fname: str) -> None:
        self._backend_for_key(fname).delete(fname)

    @api.model
    def _storage_delete_multi(self, fnames: Collection[str]) -> None:
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
        if file_type and file_type.startswith("text/"):
            text = bin_data[: self._INDEX_MAX_BYTES].decode("utf-8", errors="ignore")
            words = re.findall(r"[^\x00-\x1f\x7f-\x9f]{4,}", text)
            return "\n".join(words)
        return None

    @api.model
    def _extract_index_content(
        self, bin_data: bytes, mimetype: str, checksum: str | None = None
    ) -> str | None:
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
        if mimetype and mimetype.startswith("text/"):
            return self._INDEX_MAX_BYTES
        return 0

    @api.model
    def _as_model_name(self, res_model: Any) -> str | None:
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
        pass

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

        # One merged mapping for both branches. They used to disagree about a
        # caller-supplied column that this method also derives: the buffered
        # branch merged ``**vals`` last, so the caller silently won, while the
        # streaming branch passed ``name=``/``mimetype=`` as keywords, so the
        # same call raised ``TypeError: got multiple values for keyword
        # argument``. Which one a caller hit depended on
        # ``_should_stream_upload``, i.e. on the mimetype of the file uploaded --
        # so the bug was invisible until someone uploaded the wrong kind of file.
        # Merging identically keeps the permissive behaviour that already worked
        # and makes it the behaviour of both paths.
        values = {"name": filename, "type": "binary", "mimetype": mimetype, **vals}
        if self._should_stream_upload(mimetype):
            return self._create_from_stream(file, **values)
        # ``values`` last, so an explicit ``raw`` still wins over the file the
        # way it did before -- the merge order is what makes the two branches
        # agree, and flipping it here would quietly change the other one.
        return self.create({"raw": file.read(), **values})

    def _create_from_stream(
        self, fileobj: Any, *, name: str, mimetype: str, **vals: Any
    ) -> Self:
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
        self.ensure_one()
        return self.type == "binary"

    @api.autovacuum
    def _audit_url_attachments(self) -> None:
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
        skipped = False
        for backend_cls in tuple(STORAGE_BACKENDS.values()):
            if backend_cls(self.env).autovacuum() is False:
                skipped = True
        return False if skipped else None

    @api.model
    def _legacy_key_domain(self) -> Domain:
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
        self._mark_for_gc_multi((fname,))

    def _mark_for_gc_multi(self, fnames: Collection[str]) -> None:
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
        if self.env.context.get("image_no_postprocess"):
            return True
        maintype, _, subtype = (mimetype or "").partition("/")
        if maintype != "image":
            return True
        subtypes, max_width, _height, _quality = self._get_image_autoresize_config()
        return not (max_width and subtype in subtypes)
