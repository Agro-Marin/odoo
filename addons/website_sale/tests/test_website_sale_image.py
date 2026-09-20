import base64
import io

from PIL import Image

from odoo.fields import Command
from odoo.tests import HttpCase, tagged

from odoo.addons.website.tests.common import HttpCaseWithWebsiteUser


def _create_image(color="black", dims=(1920, 1080), format="JPEG"):
    f = io.BytesIO()
    Image.new("RGB", dims, color).save(f, format)
    f.seek(0)
    return base64.b64encode(f.read())


@tagged("post_install", "-at_install")
class TestWebsiteSaleImage(HttpCaseWithWebsiteUser):
    def test_01_admin_shop_zoom_tour(self):
        color_red = "#CD5C5C"
        name_red = "Indian Red"

        color_green = "#228B22"
        name_green = "Forest Green"

        color_blue = "#4169E1"
        name_blue = "Royal Blue"

        self.env["product.pricelist"].sudo().search([]).action_archive()

        product_attribute = self.env["product.attribute"].create(
            {
                "name": "Beautiful Color",
                "display_type": "color",
                "value_ids": [
                    Command.create(
                        {
                            "name": name_red,
                            "html_color": color_red,
                            "sequence": 1,
                        }
                    ),
                    Command.create(
                        {
                            "name": name_green,
                            "html_color": color_green,
                            "sequence": 2,
                        }
                    ),
                    Command.create(
                        {
                            "name": name_blue,
                            "html_color": color_blue,
                            "sequence": 3,
                        }
                    ),
                ],
            }
        )

        blue_image = _create_image(color=color_blue)

        red_image = _create_image(color=color_red, dims=(800, 500))

        green_image = _create_image(color=color_green)

        image_gif = _create_image(dims=(124, 147), format="GIF")

        image_svg = base64.b64encode(b"<svg></svg>")

        image_bmp = _create_image(dims=(767, 247), format="BMP")

        image_png = _create_image(dims=(2147, 3251), format="PNG")

        template = self.env["product.template"].create(
            {
                "name": "A Colorful Image",
                "product_template_image_ids": [
                    Command.create({"name": "image 1", "image_1920": image_gif}),
                    Command.create({"name": "image 4", "image_1920": image_svg}),
                ],
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": product_attribute.id,
                            "value_ids": [Command.set(product_attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )

        line = template.attribute_line_ids
        value_red = line.product_template_value_ids[0]
        value_green = line.product_template_value_ids[1]

        product_template_attribute_values = self.env[
            "product.template.attribute.value"
        ].search([("product_tmpl_id", "=", template.id)])

        for val in product_template_attribute_values:
            if val.name == name_red:
                val.price_extra = 10
            else:
                val.price_extra = 20

        product_red = template._get_variant_for_combination(value_red)
        product_red.write(
            {
                "image_1920": blue_image,
                "product_variant_image_ids": [
                    (0, 0, {"name": "image 2", "image_1920": image_bmp})
                ],
            }
        )

        self.assertEqual(template.image_1920, blue_image)

        product_green = template._get_variant_for_combination(value_green)
        product_green.write(
            {
                "image_1920": green_image,
                "product_variant_image_ids": [
                    (0, 0, {"name": "image 3", "image_1920": image_png})
                ],
            }
        )

        product_red.image_1920 = red_image

        self.assertTrue(template.can_image_1024_be_zoomed)
        self.assertFalse(
            template.product_template_image_ids[0].can_image_1024_be_zoomed
        )
        self.assertFalse(
            template.product_template_image_ids[1].can_image_1024_be_zoomed
        )
        self.assertFalse(product_red.can_image_1024_be_zoomed)
        self.assertFalse(
            product_red.product_variant_image_ids[0].can_image_1024_be_zoomed
        )
        self.assertTrue(product_green.can_image_1024_be_zoomed)
        self.assertTrue(
            product_green.product_variant_image_ids[0].can_image_1024_be_zoomed
        )

        jpeg_blue = (65, 105, 227)
        jpeg_red = (205, 93, 92)
        jpeg_green = (34, 139, 34)

        image = Image.open(io.BytesIO(base64.b64decode(template.image_1920)))
        self.assertEqual(image.size, (1920, 1080))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_blue, "blue"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_red.image_1920)))
        self.assertEqual(image.size, (800, 500))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_red, "red"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_green.image_1920)))
        self.assertEqual(image.size, (1920, 1080))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_green, "green"
        )

        image = Image.open(io.BytesIO(base64.b64decode(template.image_1024)))
        self.assertEqual(image.size, (1024, 576))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_blue, "blue"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_red.image_1024)))
        self.assertEqual(image.size, (800, 500))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_red, "red"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_green.image_1024)))
        self.assertEqual(image.size, (1024, 576))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_green, "green"
        )

        image = Image.open(io.BytesIO(base64.b64decode(template.image_512)))
        self.assertEqual(image.size, (512, 288))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_blue, "blue"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_red.image_512)))
        self.assertEqual(image.size, (512, 320))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_red, "red"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_green.image_512)))
        self.assertEqual(image.size, (512, 288))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_green, "green"
        )

        image = Image.open(io.BytesIO(base64.b64decode(template.image_256)))
        self.assertEqual(image.size, (256, 144))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_blue, "blue"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_red.image_256)))
        self.assertEqual(image.size, (256, 160))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_red, "red"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_green.image_256)))
        self.assertEqual(image.size, (256, 144))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_green, "green"
        )

        image = Image.open(io.BytesIO(base64.b64decode(template.image_128)))
        self.assertEqual(image.size, (128, 72))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_blue, "blue"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_red.image_128)))
        self.assertEqual(image.size, (128, 80))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_red, "red"
        )
        image = Image.open(io.BytesIO(base64.b64decode(product_green.image_128)))
        self.assertEqual(image.size, (128, 72))
        self.assertEqual(
            image.getpixel((image.size[0] / 2, image.size[1] / 2)), jpeg_green, "green"
        )

        self.env["ir.ui.view"].with_context(active_test=False).search(
            [("key", "=", "website_sale.product_picture_magnify_click")]
        ).write({"active": True})

        self.env["product.pricelist"].search([]).action_archive()

        self.start_tour("/", "shop_zoom", login="website_user")

        template.image_1920 = False
        product_red.unlink()
        self.assertEqual(template.image_1920, red_image)

        self.env["product.product"].create(
            {
                "product_tmpl_id": template.id,
                "image_1920": green_image,
            }
        ).unlink()
        self.assertEqual(template.image_1920, red_image)

        self.assertEqual(product_green._get_images()[0].image_1920, green_image)

        product_green.image_variant_1920 = False
        images = product_green._get_images()
        image_png = Image.open(io.BytesIO(base64.b64decode(images[1].image_1920)))
        self.assertEqual(images[0].image_1920, red_image)
        self.assertEqual(image_png.size, (1268, 1920))
        self.assertEqual(images[2].image_1920, image_gif)
        self.assertEqual(images[3].image_1920, image_svg)

        additionnal_context = {"default_product_tmpl_id": template.id}

        product = self.env["product.product"].create(
            {
                "product_tmpl_id": template.id,
            }
        )

        product_image = (
            self.env["product.image"]
            .with_context(**additionnal_context)
            .create(
                [
                    {
                        "name": "Template image",
                        "image_1920": red_image,
                    },
                    {
                        "name": "Variant image",
                        "image_1920": blue_image,
                        "product_variant_id": product.id,
                    },
                ]
            )
        )

        template_image = product_image.filtered(lambda i: i.name == "Template image")
        variant_image = product_image.filtered(lambda i: i.name == "Variant image")

        self.assertEqual(template_image.product_tmpl_id.id, template.id)
        self.assertFalse(template_image.product_variant_id.id)
        self.assertFalse(variant_image.product_tmpl_id.id)
        self.assertEqual(variant_image.product_variant_id.id, product.id)

    def test_02_image_holder(self):
        image = _create_image(color="#FF0000", dims=(800, 500))

        product_attribute = self.env["product.attribute"].create(
            {
                "name": "Beautiful Color",
                "display_type": "color",
                "value_ids": [
                    Command.create(
                        {
                            "name": "Red",
                            "sequence": 1,
                        }
                    ),
                    Command.create(
                        {
                            "name": "Green",
                            "sequence": 2,
                        }
                    ),
                    Command.create(
                        {
                            "name": "Blue",
                            "sequence": 3,
                        }
                    ),
                ],
            }
        )

        template = (
            self.env["product.template"]
            .with_context(create_product_product=False)
            .create(
                {
                    "name": "Test subject",
                }
            )
        )

        self.assertEqual(template, template._get_image_holder())

        line = self.env["product.template.attribute.line"].create(
            [
                {
                    "attribute_id": product_attribute.id,
                    "product_tmpl_id": template.id,
                    "value_ids": [Command.set(product_attribute.value_ids.ids)],
                }
            ]
        )
        value_red = line.product_template_value_ids[0]
        product_red = template._get_variant_for_combination(value_red)
        product_red.image_variant_1920 = image

        value_green = line.product_template_value_ids[1]
        product_green = template._get_variant_for_combination(value_green)
        product_green.image_variant_1920 = image

        self.assertEqual(product_red, template._get_image_holder())

        product_red.action_archive()

        self.assertEqual(product_green, template._get_image_holder())

        template.image_1920 = image

        self.assertEqual(template, template._get_image_holder())


@tagged("post_install", "-at_install")
class TestWebsiteSaleRemoveImage(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        color_blue = "#4169E1"
        name_blue = "Royal Blue"
        color_red = "#CD5C5C"
        name_red = "Indian Red"
        color_green = "#228B22"

        cls.env["ir.attachment"].create(
            {
                "public": True,
                "name": "green.jpg",
                "type": "binary",
                "datas": _create_image(color=color_green),
            }
        )

        cls.product_attribute = cls.env["product.attribute"].create(
            {
                "name": "Beautiful Color",
                "display_type": "color",
            }
        )

        cls.attr_values = cls.env["product.attribute.value"].create(
            [
                {
                    "name": name_blue,
                    "attribute_id": cls.product_attribute.id,
                    "html_color": color_blue,
                    "sequence": 1,
                },
                {
                    "name": name_red,
                    "attribute_id": cls.product_attribute.id,
                    "html_color": color_red,
                    "sequence": 2,
                },
            ]
        )

        cls.template = (
            cls.env["product.template"]
            .with_context(create_product_product=False)
            .create(
                {
                    "name": "Test Remove Image",
                    "image_1920": _create_image(color=color_blue),
                }
            )
        )

    def test_website_sale_add_and_remove_main_product_image_no_variant(self):
        self.product = self.env["product.product"].create(
            {
                "product_tmpl_id": self.template.id,
            }
        )

        self.start_tour(
            self.env["website"].get_client_action_url("/"),
            "add_and_remove_main_product_image_no_variant",
            login="admin",
        )
        self.assertFalse(self.template.image_1920)
        self.assertFalse(self.product.image_1920)

    def test_website_sale_remove_main_product_image_with_variant(self):
        self.env["product.template.attribute.line"].create(
            [
                {
                    "attribute_id": self.product_attribute.id,
                    "product_tmpl_id": self.template.id,
                    "value_ids": [(6, 0, self.attr_values.ids)],
                }
            ]
        )
        self.product = self.env["product.product"].create(
            {
                "product_tmpl_id": self.template.id,
            }
        )
        self.start_tour(
            self.env["website"].get_client_action_url("/"),
            "remove_main_product_image_with_variant",
            login="admin",
        )
        self.assertFalse(self.template.image_1920)
        self.assertFalse(self.product.image_1920)
