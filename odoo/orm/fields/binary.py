import base64
import binascii
import contextlib
import functools
import typing
import warnings
from operator import attrgetter
from typing import override

from odoo.exceptions import UserError
from odoo.libs.filesystem import guess_mimetype
from odoo.tools import SQL, human_size
from odoo.tools.image import image_process

from .base import Field

if typing.TYPE_CHECKING:
    from odoo.tools import Query

    from .._typing import ModelLike
    from ..models import BaseModel

_BINARY = memoryview

_SVG_MAGIC_BYTES = frozenset({b"P", b"<"})


class Binary(Field[bytes | typing.Literal[False]]):
    """Encapsulates binary content (e.g. a file).

    :param bool attachment: whether the field should be stored as `ir_attachment`
        or in a column of the model's table (default: ``True``).
    :param str bin_size_field: name of an integer field already holding the
        content's byte length. Under ``bin_size`` it is read instead of
        computing the content — see :meth:`compute_value`. The field must be
        listed in the ``depends`` of the compute, so the reported size is
        invalidated with the content it describes.
    """

    type = "binary"

    prefetch = False
    _depends_context = ("bin_size",)
    attachment = True
    bin_size_field: str = ""

    @functools.cached_property
    def column_type(self):
        return None if self.attachment else ("bytea", "bytea")

    @override
    def get_depends(
        self, model: BaseModel
    ) -> tuple[typing.Iterable[str], typing.Iterable[str]]:
        """Add the field-scoped ``bin_size_<name>`` flag to the cache key.

        ``read``, :meth:`compute_value`, :meth:`convert_to_cache` and
        :meth:`get_column_update` all honour ``bin_size_<name>`` alongside the
        global ``bin_size``, but only the global one was declared here — so both
        contexts shared ONE cache entry. Reading a field under
        ``bin_size_<name>`` therefore wrote the human size string into the entry
        every plain reader uses: after one such read, ``record.raw`` returned
        ``b"1.96 Kb"`` for a caller with no ``bin_size`` in context at all.

        Contexts that set neither flag key exactly as before, so this only
        separates the entries that were being conflated.
        """
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
        """Return the raw binary bytes for ``record``, bypassing bin_size."""
        bin_size_name = "bin_size_" + self.name
        record = record.with_context(**{"bin_size": False, bin_size_name: False})
        value = self._get_cache(record.env)[record.id]
        return self.convert_to_column(value, record, validate=False)

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> bytes | None:
        if isinstance(value, _BINARY):
            return bytes(value)
        if isinstance(value, str):
            return value.encode()
        if isinstance(value, int) and (
            record.env.context.get("bin_size")
            or record.env.context.get("bin_size_" + self.name)
        ):
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
    def compute_value(self, records: ModelLike) -> None:
        """Compute the field, reporting a human size instead under ``bin_size``.

        By default the size is derived FROM the value: it is computed in full,
        then discarded in favour of its length. Two costs come with that.

        The value still has to be produced, which is what ``bin_size`` exists to
        avoid — reading ``ir.attachment.datas`` on 20 half-megabyte rows read all
        10 MB back off the filestore to report a number the ``file_size`` column
        already held (30 ms against 0.5 ms).

        And its encoding has to be guessed to size it: base64 for a computed
        field (the ``datas`` convention), raw bytes for a column. The guess is
        wrong for ``ir.attachment.raw``, whose raw bytes decode as base64
        whenever their length is a multiple of four and they contain nothing
        else, so a 5000-byte file reported ``3.66 Kb`` while a 4999-byte one
        reported ``4.88 Kb`` — under-reporting by a quarter, or not, depending on
        the payload.

        ``bin_size_field`` removes both: the size is read from the field holding
        it and the compute never runs. A compute cannot do this for itself —
        :meth:`mark_dirty` strips ``bin_size`` before caching, so anything it
        assigns lands in the full-value cache instead.
        """
        bin_size_name = "bin_size_" + self.name
        under_bin_size = records.env.context.get("bin_size") or records.env.context.get(
            bin_size_name
        )
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
            super().compute_value(records_no_bin_size)
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
            super().compute_value(records)

    @override
    def read(self, records: BaseModel) -> None:
        """Read an attachment-backed field out of its ``ir.attachment`` rows.

        The size flags are read from the HOST field's context and answered from
        ``file_size``; the attachment is then read through
        ``ir.attachment._unsized()``, which clears every ``bin_size`` axis.

        Both halves were missing. The per-field flag ``bin_size_<name>`` was
        ignored here although :meth:`compute_value` and ``_fetch_query`` both
        honour it, so the same flag shortened a column-stored or computed binary
        field and did nothing to an attachment-backed one — while
        :meth:`get_depends` still keyed a separate cache entry on it. And the
        attachment was read under whatever context the host carried, so
        ``bin_size_datas`` — a flag scoped to ``ir.attachment.datas``, naming a
        field the caller never asked for — made ``partner.image_1920`` return
        ``b"70.00 bytes"``. That value lands in the entry keyed by ``bin_size``
        and ``bin_size_image_1920``, neither of which is set, so it is served to
        every later plain reader in the transaction: the cross-field poisoning
        :meth:`get_depends` fixed for one field, arriving through the storage
        model instead.
        """

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
        attachments = records.env["ir.attachment"].sudo()._unsized()
        data = {
            att.res_id: (_encode(human_size(att.file_size)) if bin_size else att.datas)
            for att in attachments.search_fetch(domain)
        }
        self._insert_cache(records, map(data.get, records._ids))

    @override
    def create(self, record_values: list[tuple[BaseModel, typing.Any]]) -> None:
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
    """Encapsulates an image, extending :class:`Binary`.

    If image size is greater than the ``max_width``/``max_height`` limit of pixels, the image will be
    resized to the limit by keeping aspect ratio.

    :param int max_width: the maximum width of the image (default: ``0``, no limit)
    :param int max_height: the maximum height of the image (default: ``0``, no limit)
    :param bool verify_resolution: whether the image resolution should be verified
        to ensure it doesn't go over the maximum image resolution (default: ``True``).
        See :class:`odoo.tools.image.ImageProcess` for maximum image resolution (default: ``50e6``).

    .. note::

        If no ``max_width``/``max_height`` is specified (or is set to 0) and ``verify_resolution`` is False,
        the field content won't be verified at all and a :class:`Binary` field should be used.
    """

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
    def create(self, record_values: list[tuple[BaseModel, typing.Any]]) -> None:
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
            img = base64.b64decode(value or "") or False
        except Exception as e:
            raise UserError(env._("Image is not encoded in base64.")) from e

        if img and guess_mimetype(img, "") == "image/webp":
            if not self.max_width and not self.max_height:
                return value
            Attachment = env["ir.attachment"]
            checksum = Attachment._content_checksum(img)
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
                    img,
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
        """Override to resize the related value before saving it on self."""
        try:
            return self._image_process(super()._process_related(value, env), env)
        except UserError:
            return False
