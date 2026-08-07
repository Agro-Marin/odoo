import base64
import io

from PIL import Image, ImageDraw, PngImagePlugin

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tools import image as tools


def img_open(data):
    return Image.open(io.BytesIO(data))


class TestImage(TransactionCase):
    def setUp(self):
        super().setUp()
        self.bg_color = (135, 90, 123)
        self.fill_color = (0, 160, 157)

        self.img_1x1_png = base64.b64decode(
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"
        )
        self.img_svg = b"<svg></svg>"
        self.img_1920x1080_jpeg = tools.image_apply_opt(
            Image.new("RGB", (1920, 1080)), "JPEG"
        )
        self.img_exif_jpg = base64.b64decode(
            b"""/9j/4AAQSkZJRgABAQAAAQABAAD/4QDQRXhpZgAATU0AKgAAAAgABgESAAMAAAABAAYAAAEaAAUA
                                  AAABAAAAVgEbAAUAAAABAAAAXgEoAAMAAAABAAEAAAITAAMAAAABAAEAAIdpAAQAAAABAAAAZgAA
                                  AAAAAAABAAAAAQAAAAEAAAABAAWQAAAHAAAABDAyMzGRAQAHAAAABAECAwCgAAAHAAAABDAxMDCg
                                  AQADAAAAAf//AACkMgAFAAAABAAAAKgAAAAAAAABjwAAAGQAAAGPAAAAZAAAAAkAAAAFAAAACQAA
                                  AAX/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAx
                                  NDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy
                                  MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAADAAYDASIAAhEBAxEB/8QAHwAAAQUBAQEB
                                  AQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1Fh
                                  ByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZ
                                  WmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG
                                  x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAEC
                                  AwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHB
                                  CSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0
                                  dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX
                                  2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iiigD//2Q=="""
        )

        image = Image.new("RGB", (1920, 1080), color=self.bg_color)
        offset = (image.size[0] - image.size[1]) / 2
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            xy=[(offset, 0), (image.size[0] - offset, image.size[1])],
            fill=self.fill_color,
        )
        self.img_1920x1080_png = tools.image_apply_opt(image, "PNG")

        image = Image.new("RGB", (1080, 1920), color=self.bg_color)
        offset = (image.size[1] - image.size[0]) / 2
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            xy=[(0, offset), (image.size[0], image.size[1] - offset)],
            fill=self.fill_color,
        )
        self.img_1080x1920_png = tools.image_apply_opt(image, "PNG")

    def test_00_base64_to_image(self):
        image = img_open(self.img_1x1_png)
        self.assertEqual(
            type(image),
            PngImagePlugin.PngImageFile,
            "base64 as bytes, correct format",
        )
        self.assertEqual(image.size, (1, 1), "base64 as bytes, correct size")

        with self.assertRaises(
            UserError,
            msg="This file could not be decoded as an image file. Please try with a different file.",
        ):
            image = tools.base64_to_image(b"oazdazpodazdpok")

        with self.assertRaises(
            UserError,
            msg="This file could not be decoded as an image file. Please try with a different file.",
        ):
            image = tools.base64_to_image(b"oazdazpodazdpokd")

    def test_01_image_to_base64(self):
        image = Image.new("RGB", (1, 1))
        image_base64 = tools.image_to_base64(image, "PNG")
        self.assertEqual(image_base64, base64.b64encode(self.img_1x1_png))

    def test_02_image_fix_orientation(self):

        blue = (0, 0, 255)
        yellow = (255, 255, 0)
        green = (0, 255, 0)
        pink = (255, 0, 255)
        size = 50
        expected = (blue, yellow, green, pink)

        self._orientation_test(1, (blue, yellow, green, pink), size, expected)
        self._orientation_test(2, (yellow, blue, pink, green), size, expected)
        self._orientation_test(3, (pink, green, yellow, blue), size, expected)
        self._orientation_test(4, (green, pink, blue, yellow), size, expected)
        self._orientation_test(5, (blue, green, yellow, pink), size, expected)
        self._orientation_test(6, (yellow, pink, blue, green), size, expected)
        self._orientation_test(7, (pink, yellow, green, blue), size, expected)
        self._orientation_test(8, (green, blue, pink, yellow), size, expected)

    def test_03_image_fix_orientation_exif(self):
        image = img_open(self.img_exif_jpg)
        self.assertEqual(image.size, (6, 3))
        image = tools.image_fix_orientation(image)
        self.assertEqual(image.size, (3, 6))

    def test_10_image_process_source(self):
        self.assertFalse(tools.image_process(False), "return False if source is falsy")
        self.assertEqual(
            tools.image_process(self.img_svg),
            self.img_svg,
            "return source if format is SVG",
        )

        with self.assertRaises(
            UserError,
            msg="This file could not be decoded as an image file. Please try with a different file.",
        ):
            tools.image_process(b"oazdazpodazdpokd", quality=95)

        image = img_open(tools.image_process(self.img_1920x1080_jpeg, quality=95))
        self.assertEqual(image.size, (1920, 1080), "OK return the image")

    def test_11_image_process_size(self):

        tests = [
            (
                self.img_1920x1080_jpeg,
                (192, 108),
                (192, 108),
                "resize to given size",
            ),
            (
                self.img_1920x1080_jpeg,
                (1920, 1080),
                (1920, 1080),
                "same size, no change",
            ),
            (
                self.img_1920x1080_jpeg,
                (192, None),
                (192, 108),
                "set height from ratio",
            ),
            (
                self.img_1920x1080_jpeg,
                (0, 108),
                (192, 108),
                "set width from ratio",
            ),
            (self.img_1920x1080_jpeg, (192, 200), (192, 108), "adapt to width"),
            (
                self.img_1920x1080_jpeg,
                (400, 108),
                (192, 108),
                "adapt to height",
            ),
            (
                self.img_1920x1080_jpeg,
                (3000, 2000),
                (1920, 1080),
                "don't resize above original, both set",
            ),
            (
                self.img_1920x1080_jpeg,
                (3000, False),
                (1920, 1080),
                "don't resize above original, width set",
            ),
            (
                self.img_1920x1080_jpeg,
                (None, 2000),
                (1920, 1080),
                "don't resize above original, height set",
            ),
            (
                self.img_1080x1920_png,
                (3000, 192),
                (108, 192),
                "vertical image, resize if below",
            ),
        ]

        count = 0
        for test in tests:
            image = img_open(tools.image_process(test[0], size=test[1]))
            self.assertEqual(image.size, test[2], test[3])
            count += 1
        self.assertEqual(count, 10, "ensure the loop is ran")

    def test_12_image_process_verify_resolution(self):
        res = tools.image_process(self.img_1920x1080_jpeg, verify_resolution=True)
        self.assertNotEqual(res, False, "size ok")
        image_excessive = tools.image_apply_opt(Image.new("RGB", (50001, 1000)), "PNG")
        with self.assertRaises(UserError, msg="size excessive"):
            tools.image_process(image_excessive, verify_resolution=True)

    def test_13_image_process_quality(self):

        image = tools.image_apply_opt(Image.new("RGBA", (1080, 1920)), "PNG")
        res = tools.image_process(image)
        self.assertLessEqual(len(res), len(image))

        image = tools.image_apply_opt(Image.new("P", (1080, 1920)), "PNG")
        res = tools.image_process(image)
        self.assertLessEqual(len(res), len(image))

        res = tools.image_process(self.img_1920x1080_jpeg)
        self.assertLessEqual(len(res), len(self.img_1920x1080_jpeg))

        pil_image = Image.new("RGB", (1920, 1080), color=self.bg_color)
        ImageDraw.Draw(pil_image).ellipse(
            xy=[(400, 0), (1500, 1080)],
            fill=self.fill_color,
            outline=(240, 25, 40),
            width=10,
        )
        image = tools.image_apply_opt(pil_image, "JPEG")
        res = tools.image_process(image, quality=50)
        self.assertLess(
            len(res),
            len(image),
            "Low quality image should be smaller than original",
        )
        res = tools.image_process(image, quality=99)
        self.assertEqual(
            len(res),
            len(image),
            "Original should be returned if size increased",
        )

        image = tools.image_apply_opt(Image.new("RGB", (1080, 1920)), "GIF")
        res = tools.image_process(image)
        self.assertLessEqual(len(res), len(image))

    def test_14_image_process_crop(self):

        fill = 0
        bg = 1

        small_width = tools.image_apply_opt(Image.new("RGBA", (1, 16)), "PNG")
        small_height = tools.image_apply_opt(Image.new("RGBA", (16, 1)), "PNG")

        tests = [
            (
                self.img_1920x1080_png,
                None,
                None,
                (1920, 1080),
                (fill, fill, bg, bg),
                "horizontal, verify initial",
            ),
            (
                self.img_1920x1080_png,
                (2000, 2000),
                "center",
                (1080, 1080),
                (fill, fill, fill, fill),
                "horizontal, crop biggest possible",
            ),
            (
                self.img_1920x1080_png,
                (2000, 4000),
                "center",
                (540, 1080),
                (fill, fill, fill, fill),
                "horizontal, size vertical, limit height",
            ),
            (
                self.img_1920x1080_png,
                (4000, 2000),
                "center",
                (1920, 960),
                (fill, fill, bg, bg),
                "horizontal, size horizontal, limit width",
            ),
            (
                self.img_1920x1080_png,
                (512, 512),
                "center",
                (512, 512),
                (fill, fill, fill, fill),
                "horizontal, type center",
            ),
            (
                self.img_1920x1080_png,
                (512, 512),
                "top",
                (512, 512),
                (fill, fill, fill, fill),
                "horizontal, type top",
            ),
            (
                self.img_1920x1080_png,
                (512, 512),
                "bottom",
                (512, 512),
                (fill, fill, fill, fill),
                "horizontal, type bottom",
            ),
            (
                self.img_1920x1080_png,
                (512, 512),
                "wrong",
                (512, 512),
                (fill, fill, fill, fill),
                "horizontal, wrong crop value, use center",
            ),
            (
                self.img_1920x1080_png,
                (192, 0),
                None,
                (192, 108),
                (fill, fill, bg, bg),
                "horizontal, not cropped, just do resize",
            ),
            (
                small_height,
                (25, 50),
                "center",
                (1, 1),
                (fill, fill, fill, fill),
                "horizontal, small height, size vertical",
            ),
            (
                self.img_1080x1920_png,
                None,
                None,
                (1080, 1920),
                (bg, bg, fill, fill),
                "vertical, verify initial",
            ),
            (
                self.img_1080x1920_png,
                (2000, 2000),
                "center",
                (1080, 1080),
                (fill, fill, fill, fill),
                "vertical, crop biggest possible",
            ),
            (
                self.img_1080x1920_png,
                (2000, 4000),
                "center",
                (960, 1920),
                (bg, bg, fill, fill),
                "vertical, size vertical, limit height",
            ),
            (
                self.img_1080x1920_png,
                (4000, 2000),
                "center",
                (1080, 540),
                (fill, fill, fill, fill),
                "vertical, size horizontal, limit width",
            ),
            (
                self.img_1080x1920_png,
                (512, 512),
                "center",
                (512, 512),
                (fill, fill, fill, fill),
                "vertical, type center",
            ),
            (
                self.img_1080x1920_png,
                (512, 512),
                "top",
                (512, 512),
                (bg, fill, fill, fill),
                "vertical, type top",
            ),
            (
                self.img_1080x1920_png,
                (512, 512),
                "bottom",
                (512, 512),
                (fill, bg, fill, fill),
                "vertical, type bottom",
            ),
            (
                self.img_1080x1920_png,
                (512, 512),
                "wrong",
                (512, 512),
                (fill, fill, fill, fill),
                "vertical, wrong crop value, use center",
            ),
            (
                self.img_1080x1920_png,
                (108, 0),
                None,
                (108, 192),
                (bg, bg, fill, fill),
                "vertical, not cropped, just do resize",
            ),
            (
                small_width,
                (50, 25),
                "center",
                (1, 1),
                (fill, fill, fill, fill),
                "vertical, small width, size horizontal",
            ),
        ]

        count = 0
        for test in tests:
            count += 1
            image = img_open(
                tools.image_process(test[0], size=test[1], crop=test[2], quality=95)
            )
            self.assertEqual(image.size, test[3], "%s - correct size" % test[5])

            half_width, half_height = image.size[0] / 2, image.size[1] / 2
            top, bottom, left, right = (
                0,
                image.size[1] - 1,
                0,
                image.size[0] - 1,
            )
            px = (half_width, top)
            self.assertEqual(
                image.getpixel(px),
                test[4][0],
                "%s - color top (%s, %s)" % (test[5], px[0], px[1]),
            )
            px = (half_width, bottom)
            self.assertEqual(
                image.getpixel(px),
                test[4][1],
                "%s - color bottom (%s, %s)" % (test[5], px[0], px[1]),
            )
            px = (left, half_height)
            self.assertEqual(
                image.getpixel(px),
                test[4][2],
                "%s - color left (%s, %s)" % (test[5], px[0], px[1]),
            )
            px = (right, half_height)
            self.assertEqual(
                image.getpixel(px),
                test[4][3],
                "%s - color right (%s, %s)" % (test[5], px[0], px[1]),
            )

        self.assertEqual(count, 2 * 10, "ensure the loop is ran")

    def test_15_image_process_colorize(self):

        image_rgba = Image.new("RGBA", (1, 1))
        self.assertEqual(image_rgba.mode, "RGBA")
        self.assertEqual(image_rgba.getpixel((0, 0)), (0, 0, 0, 0))
        rgba = tools.image_apply_opt(image_rgba, "PNG")

        image = img_open(tools.image_process(rgba, colorize=True))
        self.assertEqual(image.mode, "RGB")
        self.assertNotEqual(image.getpixel((0, 0)), (0, 0, 0))

    def test_16_image_process_format(self):

        image = img_open(
            tools.image_process(self.img_1920x1080_jpeg, output_format="PNG")
        )
        self.assertEqual(image.format, "PNG", "change format to PNG")

        image = img_open(tools.image_process(self.img_1x1_png, output_format="JpEg"))
        self.assertEqual(
            image.format, "JPEG", "change format to JPEG (case insensitive)"
        )

        image = img_open(
            tools.image_process(self.img_1920x1080_jpeg, output_format="BMP")
        )
        self.assertEqual(image.format, "PNG", "change format to BMP converted to PNG")

        image_1080_1920_rgba = tools.image_apply_opt(
            Image.new("RGBA", (108, 192)), "PNG"
        )
        image = img_open(
            tools.image_process(image_1080_1920_rgba, output_format="jpeg")
        )
        self.assertEqual(image.format, "JPEG", "change format PNG with RGBA to JPEG")

        image_1080_1920_tiff = tools.image_apply_opt(
            Image.new("RGB", (108, 192)), "TIFF"
        )
        image = img_open(tools.image_process(image_1080_1920_tiff, quality=95))
        self.assertEqual(image.format, "JPEG", "unsupported format to JPEG")

    def test_17_get_webp_size(self):
        webp_lossy = (
            b"RIFFhv\x00\x00WEBPVP8 \\v\x00\x00\xd2\xbe\x01\x9d\x01*&\x02p\x01>\xd5"
        )
        size = tools.get_webp_size(webp_lossy)
        self.assertEqual((550, 368), size, "Wrong resolution for lossy webp")
        webp_lossless = b"RIFF\xba\x84\x00\x00WEBPVP8L\xad\x84\x00\x00/\xa4\x81(\x10MHr\x1bI\x92\xa4"
        size = tools.get_webp_size(webp_lossless)
        self.assertEqual((421, 163), size, "Wrong resolution for lossless webp")
        webp_extended = b"RIFF\x80\xce\x00\x00WEBPVP8X\n\x00\x00\x00\x10\x00\x00\x00\x1f\x03\x00W\x02\x00AL"
        size = tools.get_webp_size(webp_extended)
        self.assertEqual((800, 600), size, "Wrong resolution for extended webp")

    def test_20_image_data_uri(self):
        self.assertEqual(
            tools.image_data_uri(base64.b64encode(self.img_1x1_png)),
            "data:image/png;base64,"
            + base64.b64encode(self.img_1x1_png).decode("ascii"),
        )

    def test_21_image_guess_size_from_field_name(self):
        f = tools.image_guess_size_from_field_name
        self.assertEqual(f(""), (0, 0))
        self.assertEqual(f("custom_field"), (0, 0))
        self.assertEqual(f("x_field"), (0, 0))
        self.assertEqual(f("x_studio_image_1"), (0, 0))
        self.assertEqual(f("x_studio_image_32"), (0, 0))
        self.assertEqual(f("image_15"), (0, 0))
        self.assertEqual(f("image_16"), (16, 16))
        self.assertEqual(f("image_32"), (32, 32))
        self.assertEqual(f("image_1920_1080"), (1080, 1080))
        self.assertEqual(f("image_32.5"), (0, 0))
        self.assertEqual(f("image32"), (0, 0))

    def _assertAlmostEqualSequence(self, rgb1, rgb2, delta=10):
        self.assertEqual(len(rgb1), len(rgb2))
        for index, t in enumerate(zip(rgb1, rgb2, strict=False)):
            self.assertAlmostEqual(
                t[0],
                t[1],
                delta=delta,
                msg="%s vs %s at %d" % (rgb1, rgb2, index),
            )

    def _get_exif_colored_square(self, orientation, colors, size):
        image = Image.new("RGB", (size, size), color=self.bg_color)
        draw = ImageDraw.Draw(image)
        draw.rectangle(xy=[(0, 0), (size // 2, size // 2)], fill=colors[0])
        draw.rectangle(xy=[(size // 2, 0), (size, size // 2)], fill=colors[1])
        draw.rectangle(xy=[(0, size // 2), (size // 2, size)], fill=colors[2])
        draw.rectangle(xy=[(size // 2, size // 2), (size, size)], fill=colors[3])
        exif = (
            b"Exif\x00\x00II*\x00\x08\x00\x00\x00\x01\x00\x12\x01\x03\x00\x01\x00\x00\x00"
            + bytes([orientation])
            + b"\x00\x00\x00\x00\x00\x00\x00"
        )
        return tools.image_apply_opt(image, "JPEG", exif=exif)

    def _orientation_test(self, orientation, colors, size, expected):
        image = self._get_exif_colored_square(orientation, colors, size)
        fixed_image = tools.image_fix_orientation(img_open(image))
        self._assertAlmostEqualSequence(fixed_image.getpixel((0, 0)), expected[0])
        self._assertAlmostEqualSequence(
            fixed_image.getpixel((size - 1, 0)), expected[1]
        )
        self._assertAlmostEqualSequence(
            fixed_image.getpixel((0, size - 1)), expected[2]
        )
        self._assertAlmostEqualSequence(
            fixed_image.getpixel((size - 1, size - 1)), expected[3]
        )

    def test_ptype_image_to_jpeg(self):
        image1 = Image.new("P", (1, 1), color="red")
        image2 = Image.new("RGB", (1, 1), color="red")
        self.assertEqual(
            tools.image_apply_opt(image1, "JPEG"),
            tools.image_apply_opt(image2, "JPEG"),
        )

    def test_30_image_mixin_resize_on_write(self):
        partner = self.env["res.partner"].create(
            {
                "name": "Image Mixin",
                "image_1920": base64.b64encode(self.img_1920x1080_png),
            }
        )

        self.assertEqual(
            img_open(base64.b64decode(partner.image_1920)).size, (1920, 1080)
        )

        for field_name, bound in (
            ("image_1024", 1024),
            ("image_512", 512),
            ("image_256", 256),
            ("image_128", 128),
        ):
            value = partner[field_name]
            self.assertTrue(value, "%s should be populated" % field_name)
            width, height = img_open(base64.b64decode(value)).size
            self.assertLessEqual(width, bound, "%s width within bound" % field_name)
            self.assertLessEqual(height, bound, "%s height within bound" % field_name)
            self.assertEqual(width, bound, "%s scaled to width bound" % field_name)
