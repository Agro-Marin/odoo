import base64
import binascii
import contextlib
import functools
import typing
import warnings
from collections.abc import Sequence
from operator import attrgetter
from typing import override

from odoo.exceptions import UserError
from odoo.libs.filesystem import guess_mimetype
from odoo.tools import SQL, human_size
from odoo.tools.image import image_process

from ..domain.ast import Domain, DomainCondition, OptimizationLevel
from ..primitives import COLLECTION_TYPES
from .base import Field

if typing.TYPE_CHECKING:
    from odoo.tools import Query

    from .._typing import ModelLike
    from ..models import BaseModel

_BINARY = memoryview

_SVG_MAGIC_BYTES = frozenset({b"P", b"<"})


class Binary(Field[bytes | typing.Literal[False]]):
    type = "binary"
    is_binary = True
    cache_truthiness_matches = True

    prefetch = False
    _depends_context = ("bin_size",)
    attachment = True

    @property
    def is_attachment_backed(self) -> bool:
        return self.attachment

    @override
    def _optimize_condition(
        self, condition: DomainCondition, model: BaseModel, level: OptimizationLevel
    ) -> Domain:
        if level != OptimizationLevel.BASIC:
            return condition
        operator = condition.operator
        value = condition.value
        if self.attachment:
            is_existence_check = (
                operator in ("in", "not in")
                and isinstance(value, COLLECTION_TYPES)
                and set(value) == {False}
            )
            if not is_existence_check:
                raise condition._prepare_condition_error(
                    "Binary field stored in attachment, accepts only existence "
                    "check (('field', 'in', [False]) or its negation)"
                )
        if operator.endswith("like"):
            raise condition._prepare_condition_error(
                "Cannot use like operators with binary fields",
                error=NotImplementedError,
            )
        return condition

    bin_size_field: str = ""

    #: the field holds the file's own bytes; every other binary field holds
    #: their base64 representation, and the RPC layer expects base64
    stores_raw_bytes: bool = False

    @functools.cached_property
    def column_type(self):
        return None if self.attachment else ("bytea", "bytea")

    @override
    def get_depends(
        self, model: BaseModel
    ) -> tuple[typing.Iterable[str], typing.Iterable[str]]:
        depends, depends_context = super().get_depends(model)
        return depends, (*depends_context, "bin_size_" + self.name)

    def _get_attrs(self, model_class, name):
        attrs = super()._get_attrs(model_class, name)
        if not attrs.get("store", True):
            attrs["attachment"] = False
        return attrs

    _description_attachment = property(attrgetter("attachment"))

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> bytes | None:
        if not value:
            return None
        if isinstance(value, str):
            value = value.encode()
        if validate and value[:1] in _SVG_MAGIC_BYTES:
            try:
                decoded_value = base64.b64decode(
                    value.translate(None, delete=b"\r\n"), validate=True
                )
            except binascii.Error:
                decoded_value = value
            if (
                guess_mimetype(decoded_value).startswith("image/svg")
                and not record.env.is_system()
            ):
                raise UserError(record.env._("Only admins can upload SVG files."))
        if isinstance(value, bytes):
            return value
        try:
            return str(value).encode("ascii")
        except UnicodeEncodeError as e:
            raise UserError(
                record.env._(
                    "ASCII characters are required for %(value)s in %(field)s",
                    value=value,
                    field=self.name,
                )
            ) from e

    @override
    def get_column_update(self, record: ModelLike) -> bytes | None:
        bin_size_name = "bin_size_" + self.name
        record = record.with_context(**{"bin_size": False, bin_size_name: False})
        value = self._get_cache(record.env)[record.id]
        return self.convert_to_column(value, record, validate=False)

    def _under_bin_size(self, record: ModelLike) -> bool:
        """Whether the cache holds a human-readable size instead of content."""
        context = record.env.context
        return bool(context.get("bin_size") or context.get("bin_size_" + self.name))

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> bytes | None:
        if isinstance(value, _BINARY):
            return bytes(value)
        if isinstance(value, str):
            return value.encode()
        if isinstance(value, int) and self._under_bin_size(record):
            value = human_size(value)
            return value.encode() if value else None
        return None if value is False else value

    @override
    def convert_to_record(
        self, value: typing.Any, record: ModelLike
    ) -> bytes | typing.Literal[False]:
        if isinstance(value, _BINARY):
            return bytes(value)
        return False if value is None else value

    @override
    def convert_to_read(
        self, value: typing.Any, record: ModelLike, use_display_name: bool = True
    ) -> typing.Any:
        # read() feeds the textual RPC layers, which cannot carry bytes: every
        # binary field leaves here as a base64 str, whatever the cache holds.
        if not value:
            return False
        if not isinstance(value, bytes) or self._under_bin_size(record):
            return value
        if (self.related_field or self).stores_raw_bytes:
            value = base64.b64encode(value)
        return value.decode()

    @override
    def convert_to_write(self, value: typing.Any, record: ModelLike) -> typing.Any:
        # the generic implementation routes through convert_to_read, which now
        # base64-encodes raw bytes; a write value has to stay in the cache
        # representation the field reads back.
        return self.convert_to_cache(value, record) or False

    @override
    def compute_value(self, records: ModelLike, validate: bool = True) -> None:
        bin_size_name = "bin_size_" + self.name
        under_bin_size = self._under_bin_size(records)
        if under_bin_size and self.bin_size_field:
            field_cache = self._get_cache(records.env)
            for record in records:
                field_cache[record.id] = self.convert_to_cache(
                    human_size(record[self.bin_size_field]), record
                )
            return
        if under_bin_size:
            records_no_bin_size = records.with_context(
                **{"bin_size": False, bin_size_name: False}
            )
            super().compute_value(records_no_bin_size, validate=validate)
            field_cache_data = self._get_cache(records_no_bin_size.env)
            field_cache_size = self._get_cache(records.env)
            for record in records:
                try:
                    value = field_cache_data[record.id]
                    if not self.is_column:
                        with contextlib.suppress(TypeError, binascii.Error):
                            value = base64.b64decode(value)
                    if isinstance(value, (bytes, _BINARY)):
                        value = human_size(len(value))
                    cache_value = self.convert_to_cache(value, record)
                    field_cache_size[record.id] = cache_value
                except KeyError:
                    pass
        else:
            super().compute_value(records, validate=validate)

    @override
    def read(self, records: BaseModel) -> None:

        def _encode(s: str | bool) -> bytes | bool:
            if isinstance(s, str):
                return s.encode("utf-8")
            return s

        assert self.attachment
        domain = [
            ("res_model", "=", records._name),
            ("res_field", "=", self.name),
            ("res_id", "in", records.ids),
        ]
        context = records.env.context
        bin_size = context.get("bin_size") or context.get("bin_size_" + self.name)
        attachments = records.env["ir.attachment"].sudo()._without_bin_size()
        data = {
            att.res_id: (_encode(human_size(att.file_size)) if bin_size else att.datas)
            for att in attachments.search_fetch(domain)
        }
        self._insert_cache(records, map(data.get, records._ids))

    @override
    def create(self, record_values: Sequence[tuple[BaseModel, typing.Any]]) -> None:
        assert self.attachment
        if not record_values:
            return
        env = record_values[0][0].env
        env["ir.attachment"].sudo().create(
            [
                {
                    "name": self.name,
                    "res_model": self.model_name,
                    "res_field": self.name,
                    "res_id": record.id,
                    "type": "binary",
                    "datas": value,
                }
                for record, value in record_values
                if value
            ]
        )

    @override
    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        records = records.with_context(
            **{"bin_size": False, "bin_size_" + self.name: False}
        )
        if not self.attachment:
            super().mark_dirty(records, value)
            return

        records, cache_value = self._mark_dirty_prologue(records, value)
        if not records:
            return
        if self.store:
            not_null = self._filter_not_equal(records, None)

        self._update_cache(records, cache_value)

        if self.store and any(records._ids):
            real_records = records.filtered("id")
            atts = records.env["ir.attachment"].sudo()
            if not_null:
                atts = atts.search(
                    [
                        ("res_model", "=", self.model_name),
                        ("res_field", "=", self.name),
                        ("res_id", "in", real_records.ids),
                    ]
                )
            if value:
                atts.write({"datas": value})
                atts_records = records.browse(atts.mapped("res_id"))
                missing = real_records - atts_records
                if missing:
                    atts.create(
                        [
                            {
                                "name": self.name,
                                "res_model": record._name,
                                "res_field": self.name,
                                "res_id": record.id,
                                "type": "binary",
                                "datas": value,
                            }
                            for record in missing
                        ]
                    )
            else:
                atts.unlink()

    @override
    def condition_to_sql(
        self,
        field_expr: str,
        operator: str,
        value: typing.Any,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        if not self.attachment or field_expr != self.name:
            return super().condition_to_sql(
                field_expr, operator, value, model, alias, query
            )
        assert operator in ("in", "not in") and set(value) == {False}, (
            "Should have been done in Domain optimization"
        )
        return SQL(
            "%sEXISTS (SELECT 1 FROM ir_attachment WHERE res_model = %s AND res_field = %s AND res_id = %s)",
            SQL("NOT ") if operator == "in" else SQL(),
            model._name,
            self.name,
            model._field_to_sql(alias, "id", query),
        )


class Image(Binary):
    max_width = 0
    max_height = 0
    verify_resolution = True

    @override
    def setup(self, model: BaseModel) -> None:
        super().setup(model)
        if not model._abstract and not model._log_access:
            warnings.warn(
                f"Image field {self} requires the model to have _log_access = True",
                stacklevel=1,
            )

    @override
    def create(self, record_values: Sequence[tuple[BaseModel, typing.Any]]) -> None:
        new_record_values: list[tuple[BaseModel, typing.Any]] = []
        for record, value in record_values:
            new_value = self._image_process(value, record.env)
            new_record_values.append((record, new_value))
            cache_value = self.convert_to_cache(
                value if self.related else new_value, record
            )
            self._update_cache(record, cache_value)
        super().create(new_record_values)

    @override
    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        records = records.with_context(
            **{"bin_size": False, "bin_size_" + self.name: False}
        )
        try:
            new_value = self._image_process(value, records.env)
        except UserError:
            if not any(records._ids):
                return
            raise

        super().mark_dirty(records, new_value)
        if self.related:
            cache_value = self.convert_to_cache(value, records)
            self._update_cache(records, cache_value, dirty=True)

    @override
    def _inverse_related(self, records: BaseModel) -> None:
        super()._inverse_related(records)
        if not (self.max_width and self.max_height):
            return
        for record in records:
            value = self._process_related(record[self.name], record.env)
            self._update_cache(record, value, dirty=True)

    def _image_process(
        self, value: typing.Any, env: typing.Any
    ) -> bytes | typing.Literal[False]:
        if self.readonly and (
            (not self.max_width and not self.max_height)
            or (
                isinstance(self.related_field, Image)
                and self.max_width == self.related_field.max_width
                and self.max_height == self.related_field.max_height
            )
        ):
            return value
        try:
            img = base64.b64decode(value or "")
        except Exception as e:
            raise UserError(env._("Image is not encoded in base64.")) from e

        if img and guess_mimetype(img, "") == "image/webp":
            if not self.max_width and not self.max_height:
                return value
            Attachment = env["ir.attachment"]
            checksum = Attachment._get_content_checksum(img)
            origins = Attachment.search(
                [
                    ["id", "!=", False],
                    ["checksum", "=", checksum],
                ]
            )
            if origins:
                origin_ids = [attachment.id for attachment in origins]
                resized_domain = [
                    ["id", "!=", False],
                    ["res_model", "=", "ir.attachment"],
                    ["res_id", "in", origin_ids],
                    [
                        "description",
                        "=",
                        f"resize: {max(self.max_width, self.max_height)}",
                    ],
                ]
                resized = Attachment.sudo().search(resized_domain, limit=1)
                if resized:
                    return resized.datas or value
            return value

        return (
            base64.b64encode(
                image_process(
                    img or None,
                    size=(self.max_width, self.max_height),
                    verify_resolution=self.verify_resolution,
                )
                or b""
            )
            or False
        )

    @override
    def _process_related(
        self, value: typing.Any, env: typing.Any
    ) -> bytes | typing.Literal[False]:
        try:
            return self._image_process(super()._process_related(value, env), env)
        except UserError:
            return False
