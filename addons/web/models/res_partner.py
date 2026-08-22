import functools
import logging
from base64 import b64decode
from typing import Any

from odoo import models
from odoo.libs.facade import Proxy, ProxyAttr, ProxyFunc

_logger = logging.getLogger(__name__)


_IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "JPEG",
    b"\x89PNG": "PNG",
    b"GIF8": "GIF",
    b"BM": "BMP",
}


def _guess_image_vcard_type(data: bytes) -> str:
    for signature, vcard_type in _IMAGE_SIGNATURES.items():
        if data[: len(signature)] == signature:
            return vcard_type
    return "JPEG"


@functools.cache
def _vobject() -> tuple[Any, type]:
    import vobject.vcard

    class VBaseProxy(Proxy):
        _wrapped__ = vobject.base.VBase

        encoding_param = ProxyAttr()
        type_param = ProxyAttr()
        value = ProxyAttr(None)

    class VCardContentsProxy(Proxy):
        _wrapped__ = dict

        __delitem__ = ProxyFunc()
        __contains__ = ProxyFunc()
        get = ProxyFunc(lambda lines: [VBaseProxy(line) for line in lines])

    class VComponentProxy(Proxy):
        _wrapped__ = vobject.base.Component

        add = ProxyFunc(VBaseProxy)
        contents = ProxyAttr(VCardContentsProxy)
        serialize = ProxyFunc()

    return vobject, VComponentProxy


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _prepare_vcard(self) -> Any:
        self.ensure_one()
        vobject, VComponentProxy = _vobject()
        vcard = vobject.vCard()
        n = vcard.add("n")
        n.value = vobject.vcard.Name(family=self.name or self.complete_name or "")
        fn = vcard.add("fn")
        fn.value = self.name or self.complete_name or ""
        adr = vcard.add("adr")
        adr.value = vobject.vcard.Address(
            street=self.street or "", city=self.city or "", code=self.zip or ""
        )
        if self.state_id:
            adr.value.region = self.state_id.name
        if self.country_id:
            adr.value.country = self.country_id.name
        if self.email:
            email = vcard.add("email")
            email.value = self.email
            email.type_param = "INTERNET"
        if self.phone:
            tel = vcard.add("tel")
            tel.type_param = "work"
            tel.value = self.phone
        if self.website:
            url = vcard.add("url")
            url.value = self.website
        if self.commercial_company_name:
            org = vcard.add("org")
            org.value = [self.commercial_company_name]
        if self.function:
            function = vcard.add("title")
            function.value = self.function
        if self.avatar_512:
            photo = vcard.add("photo")
            photo_data = b64decode(self.avatar_512)
            photo.value = photo_data
            photo.encoding_param = "B"
            photo.type_param = _guess_image_vcard_type(photo_data)
        return VComponentProxy(vcard)

    def _get_vcard_file(self) -> bytes:
        return self._prepare_vcard().serialize().encode()
