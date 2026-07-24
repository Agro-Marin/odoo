import base64
import binascii
import contextlib
import functools
import typing
import warnings
from operator import attrgetter
from typing import override

from odoo.exceptions import UserError
from odoo.libs.filesystem.mimetypes import guess_mimetype
from odoo.tools import SQL, human_size
from odoo.tools.image import image_process

from .base import Field

if typing.TYPE_CHECKING:
    from odoo.tools import Query

    from .._typing import ModelLike
    from ..models import BaseModel

# Binary data is returned as memoryview by psycopg.
_BINARY = memoryview

# First byte of SVG-ish content: 'P' is '<' (0x3C) base64-encoded, '<' is a
# plaintext XML tag opening. Used to restrict SVG upload to system users.
_SVG_MAGIC_BYTES = frozenset({b"P", b"<"})


class Binary(Field[bytes | typing.Literal[False]]):
    """Encapsulates binary content (e.g. a file).

    :param bool attachment: whether the field should be stored as `ir_attachment`
        or in a column of the model's table (default: ``True``).
    """

    type = "binary"

    prefetch = False  # not prefetched by default
    _depends_context = ("bin_size",)  # depends on context (content or size)
    attachment = True  # whether value is stored in attachment

    @functools.cached_property
    def column_type(self):
        return None if self.attachment else ("bytea", "bytea")

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
        # Binaries are transferred/stored as base64 strings (legacy convention),
        # sometimes as unicode, hence the str() cast below. ASCII-only on
        # purpose: raw binary must be passed as bytes.
        if not value:
            return None
        # Detect SVG content to restrict its upload to system users.
        if isinstance(value, str):
            value = value.encode()
        if validate and value[:1] in _SVG_MAGIC_BYTES:
            try:
                decoded_value = base64.b64decode(
                    value.translate(None, delete=b"\r\n"), validate=True
                )
            except binascii.Error:
                decoded_value = value
            # Full mimetype detection
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
        # force bin_size=False to get actual data, not the size
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
            # the cache must contain bytes or memoryview, but sometimes a string
            # is given when assigning a binary field (test `TestFileSeparator`)
            return value.encode()
        if isinstance(value, int) and (
            record.env.context.get("bin_size")
            or record.env.context.get("bin_size_" + self.name)
        ):
            # If the client requests only the size of the field, we return that
            # instead of the content. Presumably a separate request will be done
            # to read the actual content, if necessary.
            value = human_size(value)
            # human_size can return False (-> None) or a string (-> encoded)
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
        bin_size_name = "bin_size_" + self.name
        if records.env.context.get("bin_size") or records.env.context.get(
            bin_size_name
        ):
            # always compute without bin_size
            records_no_bin_size = records.with_context(
                **{"bin_size": False, bin_size_name: False}
            )
            super().compute_value(records_no_bin_size)
            # manually update the bin_size cache
            field_cache_data = self._get_cache(records_no_bin_size.env)
            field_cache_size = self._get_cache(records.env)
            for record in records:
                try:
                    value = field_cache_data[record.id]
                    # don't decode non-attachments to be consistent with pg_size_pretty
                    if not self.is_column:
                        with contextlib.suppress(TypeError, binascii.Error):
                            value = base64.b64decode(value)
                    # isinstance guarantees a len()-able bytes/memoryview, and
                    # human_size(int) cannot raise — no TypeError guard needed.
                    if isinstance(value, (bytes, _BINARY)):
                        value = human_size(len(value))
                    cache_value = self.convert_to_cache(value, record)
                    # the dirty flag is independent from this assignment
                    field_cache_size[record.id] = cache_value
                except KeyError:
                    pass
        else:
            super().compute_value(records)

    @override
    def read(self, records: BaseModel) -> None:
        def _encode(s: str | bool) -> bytes | bool:
            if isinstance(s, str):
                return s.encode("utf-8")
            return s

        # values are stored in attachments, retrieve them
        assert self.attachment
        domain = [
            ("res_model", "=", records._name),
            ("res_field", "=", self.name),
            ("res_id", "in", records.ids),
        ]
        bin_size = records.env.context.get("bin_size")
        data = {
            att.res_id: (_encode(human_size(att.file_size)) if bin_size else att.datas)
            for att in records.env["ir.attachment"].sudo().search_fetch(domain)
        }
        self._insert_cache(records, map(data.get, records._ids))

    @override
    def create(self, record_values: list[tuple[BaseModel, typing.Any]]) -> None:
        assert self.attachment
        if not record_values:
            return
        # create the attachments that store the values
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
        # Reset BOTH the global and per-field bin_size keys before touching the
        # cache: convert_to_cache honors either, so leaving bin_size_<name>
        # active would size-convert an int value into a human_size string and
        # cache it as content. Mirrors get_column_update / compute_value.
        records = records.with_context(
            **{"bin_size": False, "bin_size_" + self.name: False}
        )
        if not self.attachment:
            super().mark_dirty(records, value)
            return

        # prologue: cancel pending recompute, convert, drop unmodified records
        records, cache_value = self._mark_dirty_prologue(records, value)
        if not records:
            return
        if self.store:
            not_null = self._filter_not_equal(records, None)

        self._update_cache(records, cache_value)

        # retrieve and adapt the attachments that store the values
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
                # update the existing attachments
                atts.write({"datas": value})
                atts_records = records.browse(atts.mapped("res_id"))
                # create the missing attachments
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
        # Use a correlated NOT EXISTS/EXISTS rather than NOT IN/IN: on a large
        # ir_attachment, materializing the full res_id list is a bottleneck,
        # while EXISTS lets PostgreSQL short-circuit on the first match.
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
            # when setting related image field, keep the unprocessed image in
            # cache to let the inverse method use the original image; the image
            # will be resized once the inverse has been applied
            cache_value = self.convert_to_cache(
                value if self.related else new_value, record
            )
            self._update_cache(record, cache_value)
        super().create(new_record_values)

    @override
    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        # Reset the bin_size context up front so the cache writes below land in
        # the (False,) sub-cache (unprocessed content), not size strings.
        # Binary.mark_dirty resets its own local records, which doesn't
        # propagate back to the `records` we convert/cache here.
        records = records.with_context(
            **{"bin_size": False, "bin_size_" + self.name: False}
        )
        try:
            new_value = self._image_process(value, records.env)
        except UserError:
            if not any(records._ids):
                # Invalid value on a new record: in onchange the client may send
                # the field's "bin size" instead of its content (to save
                # bandwidth). Skip the assignment; the value comes from origin.
                return
            raise

        super().mark_dirty(records, new_value)
        if self.related:
            # keep the unprocessed image in cache so the inverse method gets
            # the original (same reason as create()); resized afterwards by
            # _inverse_related
            cache_value = self.convert_to_cache(value, records)
            self._update_cache(records, cache_value, dirty=True)
        # non-related: super() already cached the processed value and marked
        # only the actually-modified records dirty; re-caching here would
        # re-mark ALL records and emit no-op UPDATEs for column-stored images

    @override
    def _inverse_related(self, records: BaseModel) -> None:
        super()._inverse_related(records)
        if not (self.max_width and self.max_height):
            return
        # the inverse has been applied with the original image; now we fix the
        # cache with the resized value
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
            # no need to process images for computed fields, or related fields
            # (when the related field already applies the same resizing) —
            # excess Pillow processing quickly leads to MemoryError on upgrades
            return value
        try:
            img = base64.b64decode(value or "") or False
        except Exception as e:
            raise UserError(env._("Image is not encoded in base64.")) from e

        if img and guess_mimetype(img, "") == "image/webp":
            if not self.max_width and not self.max_height:
                return value
            # Fetch resized version.
            Attachment = env["ir.attachment"]
            checksum = Attachment._content_checksum(img)
            origins = Attachment.search(
                [
                    ["id", "!=", False],  # No implicit condition on res_field.
                    ["checksum", "=", checksum],
                ]
            )
            if origins:
                origin_ids = [attachment.id for attachment in origins]
                resized_domain = [
                    ["id", "!=", False],  # No implicit condition on res_field.
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
                    # Fallback on non-resized image (value).
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
            # Avoid the following `write` to fail if the related image was saved
            # invalid, which can happen for pre-existing databases.
            return False
