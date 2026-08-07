"""Typed exceptions replace English-substring matching at the libs->tools seam.

``odoo.tools.image`` and ``odoo.tools.template_inheritance`` used to pick their
translated ``UserError`` / ``ValidationError`` by testing whether a hardcoded
English phrase was ``in str(exception)``.  Rewording the message in ``odoo.libs``
silently broke that routing.  The libs now raise dedicated subclasses of
``ValueError`` (so every existing ``except ValueError`` keeps working) and the
wrappers branch on the type.
"""

import unittest

from odoo.libs.image import (
    ImageDecodeError,
    ImageError,
    ImageTooLargeError,
    NotWebpError,
    base64_to_image,
    binary_to_image,
    get_webp_size,
)
from odoo.libs.image import ImageProcess as LibImageProcess
from odoo.libs.xml import XPathExpressionError


class TestImageErrorsAreTypedAndSubclassValueError(unittest.TestCase):
    def test_hierarchy(self):
        for cls in (ImageDecodeError, ImageTooLargeError, NotWebpError):
            self.assertTrue(issubclass(cls, ImageError))
            self.assertTrue(issubclass(cls, ValueError))

    def test_undecodable_bytes_raise_decode_error(self):
        with self.assertRaises(ImageDecodeError):
            binary_to_image(b"not an image")
        with self.assertRaises(ImageDecodeError):
            base64_to_image(b"////")
        with self.assertRaises(ImageDecodeError):
            LibImageProcess(b"not an image at all")

    def test_backward_compatible_except_valueerror(self):
        with self.assertRaises(ValueError):
            binary_to_image(b"nope")

    def test_not_webp_raises_notwebp_error(self):
        with self.assertRaises(NotWebpError):
            get_webp_size(b"this is clearly not a RIFF/WEBP header")

    def test_too_large_image_raises_typed_error(self):
        self.assertTrue(issubclass(ImageTooLargeError, ImageError))


class TestXPathExpressionErrorType(unittest.TestCase):
    def test_subclasses_valueerror(self):
        self.assertTrue(issubclass(XPathExpressionError, ValueError))

    def test_locate_node_raises_typed_error_on_bad_xpath(self):
        from lxml import etree

        from odoo.libs.xml import locate_node

        arch = etree.fromstring("<form/>")
        spec = etree.fromstring('<xpath expr="//[[[bad" position="replace"/>')
        with self.assertRaises(XPathExpressionError):
            locate_node(arch, spec)


if __name__ == "__main__":
    unittest.main()
