import functools
from base64 import b64encode
from datetime import UTC

from odoo import api, fields, models
from odoo.libs.colors import hsl_from_seed
from odoo.tools import file_open, html_escape
from odoo.tools.misc import limited_field_access_token

_FieldName = str


@functools.cache
def _get_placeholder_image(path: str) -> bytes:
    with file_open(path, "rb") as file:
        return file.read()


class MixinAvatar(models.AbstractModel):
    _name = "mixin.avatar"
    _inherit = ["mixin.image"]
    _description = "Avatar Mixin"
    _avatar_name_field = "name"

    avatar_1920 = fields.Image("Avatar", compute="_compute_avatar_1920")
    avatar_1024 = fields.Image("Avatar 1024", compute="_compute_avatar_1024")
    avatar_512 = fields.Image("Avatar 512", compute="_compute_avatar_512")
    avatar_256 = fields.Image("Avatar 256", compute="_compute_avatar_256")
    avatar_128 = fields.Image("Avatar 128", compute="_compute_avatar_128")


    @api.depends(lambda self: [self._avatar_name_field, "image_1920"])
    def _compute_avatar_1920(self) -> None:
        self._update_avatar("avatar_1920", "image_1920")

    @api.depends(lambda self: [self._avatar_name_field, "image_1024"])
    def _compute_avatar_1024(self) -> None:
        self._update_avatar("avatar_1024", "image_1024")

    @api.depends(lambda self: [self._avatar_name_field, "image_512"])
    def _compute_avatar_512(self) -> None:
        self._update_avatar("avatar_512", "image_512")

    @api.depends(lambda self: [self._avatar_name_field, "image_256"])
    def _compute_avatar_256(self) -> None:
        self._update_avatar("avatar_256", "image_256")

    @api.depends(lambda self: [self._avatar_name_field, "image_128"])
    def _compute_avatar_128(self) -> None:
        self._update_avatar("avatar_128", "image_128")


    def _update_avatar(self, avatar_field: _FieldName, image_field: _FieldName) -> None:
        for record in self:
            avatar = record[image_field]
            if not avatar:
                name = record[record._avatar_name_field]
                if record.id and name and name.strip():
                    avatar = record._prepare_avatar_svg()
                else:
                    avatar = b64encode(record._get_avatar_placeholder())
            record[avatar_field] = avatar

    def _prepare_avatar_svg(self) -> bytes:
        self.ensure_one()
        initial = html_escape(self[self._avatar_name_field].strip()[0].upper())
        bgcolor = hsl_from_seed(
            self[self._avatar_name_field]
            + str(
                self.create_date.replace(tzinfo=UTC).timestamp()
                if self.create_date
                else ""
            )
        )
        return b64encode(
            (
                '<?xml version="1.0" encoding="UTF-8" ?>'
                '<svg height="180" width="180" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
                f'<rect fill="{bgcolor}" height="180" width="180"/>'
                f'<text fill="#ffffff" font-size="96" text-anchor="middle" x="90" y="125" font-family="sans-serif">{initial}</text>'
                "</svg>"
            ).encode()
        )

    def _get_avatar_placeholder_path(self) -> str:
        return "base/static/img/avatar_grey.png"

    def _get_avatar_placeholder(self) -> bytes:
        return _get_placeholder_image(self._get_avatar_placeholder_path())

    def _get_avatar_128_access_token(self) -> str:
        self.ensure_one()
        return limited_field_access_token(self, "avatar_128", scope="binary")
