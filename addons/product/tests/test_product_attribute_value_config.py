import time

from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.base.tests.common import BaseCommon


class TestProductAttributeValueCommon(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.computer = cls.env["product.template"].create(
            {
                "name": "Super Computer",
                "list_price": 2000,
            }
        )

        (
            cls.ssd_attribute,
            cls.ram_attribute,
            cls.hdd_attribute,
            cls.size_attribute,
            cls.extras_attribute,
            cls.operating_system_attribute,
        ) = cls.env["product.attribute"].create(
            [
                {
                    "name": "Memory",
                    "sequence": 1,
                    "value_ids": [
                        Command.create(
                            {
                                "name": "256 GB",
                                "sequence": 1,
                            }
                        ),
                        Command.create(
                            {
                                "name": "512 GB",
                                "sequence": 2,
                            }
                        ),
                    ],
                },
                {
                    "name": "RAM",
                    "sequence": 2,
                    "value_ids": [
                        Command.create(
                            {
                                "name": "8 GB",
                                "sequence": 1,
                            }
                        ),
                        Command.create(
                            {
                                "name": "16 GB",
                                "sequence": 2,
                            }
                        ),
                        Command.create(
                            {
                                "name": "32 GB",
                                "sequence": 3,
                            }
                        ),
                    ],
                },
                {
                    "name": "HDD",
                    "sequence": 3,
                    "value_ids": [
                        Command.create(
                            {
                                "name": "1 To",
                                "sequence": 1,
                            }
                        ),
                        Command.create(
                            {
                                "name": "2 To",
                                "sequence": 2,
                            }
                        ),
                        Command.create(
                            {
                                "name": "4 To",
                                "sequence": 3,
                            }
                        ),
                    ],
                },
                {
                    "name": "Size",
                    "sequence": 4,
                    "value_ids": [
                        Command.create(
                            {
                                "name": "M",
                                "sequence": 1,
                            }
                        ),
                        Command.create(
                            {
                                "name": "L",
                                "sequence": 2,
                            }
                        ),
                        Command.create(
                            {
                                "name": "XL",
                                "sequence": 3,
                            }
                        ),
                    ],
                },
                {
                    "name": "Extras",
                    "sequence": 5,
                    "display_type": "multi",
                    "create_variant": "no_variant",
                    "value_ids": [
                        Command.create(
                            {
                                "name": "CPU overclock",
                                "sequence": 1,
                            }
                        ),
                        Command.create(
                            {
                                "name": "RAM overclock",
                                "sequence": 2,
                            }
                        ),
                    ],
                },
                {
                    "name": "Operating System",
                    "sequence": 6,
                    "display_type": "multi",
                    "create_variant": "no_variant",
                    "value_ids": [
                        Command.create(
                            {
                                "name": "Linux",
                                "sequence": 1,
                            }
                        ),
                        Command.create(
                            {
                                "name": "Windows",
                                "sequence": 2,
                            }
                        ),
                    ],
                },
            ]
        )

        cls.ssd_256, cls.ssd_512 = cls.ssd_attribute.value_ids
        cls.ram_8, cls.ram_16, cls.ram_32 = cls.ram_attribute.value_ids
        cls.hdd_1, cls.hdd_2, cls.hdd_4 = cls.hdd_attribute.value_ids
        cls.size_m, cls.size_l, cls.size_xl = cls.size_attribute.value_ids
        cls.extra_cpu, cls.extra_ram = cls.extras_attribute.value_ids
        cls.linux_operating_system, cls.windows_operating_system = (
            cls.operating_system_attribute.value_ids
        )

        cls.COMPUTER_SSD_PTAL_VALUES = {
            "product_tmpl_id": cls.computer.id,
            "attribute_id": cls.ssd_attribute.id,
            "value_ids": [Command.set([cls.ssd_256.id, cls.ssd_512.id])],
        }
        cls.COMPUTER_RAM_PTAL_VALUES = {
            "product_tmpl_id": cls.computer.id,
            "attribute_id": cls.ram_attribute.id,
            "value_ids": [Command.set([cls.ram_8.id, cls.ram_16.id, cls.ram_32.id])],
        }
        cls.COMPUTER_HDD_PTAL_VALUES = {
            "product_tmpl_id": cls.computer.id,
            "attribute_id": cls.hdd_attribute.id,
            "value_ids": [Command.set([cls.hdd_1.id, cls.hdd_2.id, cls.hdd_4.id])],
        }
        cls.COMPUTER_EXTRAS_PTAL_VALUES = {
            "product_tmpl_id": cls.computer.id,
            "attribute_id": cls.extras_attribute.id,
            "value_ids": [Command.set([cls.extra_cpu.id, cls.extra_ram.id])],
        }
        cls.COMPUTER_OPERATING_SYSTEM_VALUES = {
            "product_tmpl_id": cls.computer.id,
            "attribute_id": cls.operating_system_attribute.id,
            "value_ids": [
                Command.set(
                    [cls.windows_operating_system.id, cls.linux_operating_system.id]
                )
            ],
        }

        cls._add_computer_attribute_lines()

        cls.computer_case = cls.env["product.template"].create(
            {"name": "Super Computer Case"}
        )

        cls.computer_case_size_attribute_lines = cls.env[
            "product.template.attribute.line"
        ].create(
            {
                "product_tmpl_id": cls.computer_case.id,
                "attribute_id": cls.size_attribute.id,
                "value_ids": [
                    Command.set([cls.size_m.id, cls.size_l.id, cls.size_xl.id])
                ],
            }
        )

    @classmethod
    def _add_computer_attribute_lines(cls):
        (
            cls.computer_ssd_attribute_lines,
            cls.computer_ram_attribute_lines,
            cls.computer_hdd_attribute_lines,
            cls.computer_extras_attribute_lines,
            cls.computer_operating_system_lines,
        ) = cls.env["product.template.attribute.line"].create(
            [
                cls.COMPUTER_SSD_PTAL_VALUES,
                cls.COMPUTER_RAM_PTAL_VALUES,
                cls.COMPUTER_HDD_PTAL_VALUES,
                cls.COMPUTER_EXTRAS_PTAL_VALUES,
                cls.COMPUTER_OPERATING_SYSTEM_VALUES,
            ]
        )

        cls._setup_ssd_attribute_line()
        cls._setup_ram_attribute_line()
        cls._setup_hdd_attribute_line()

    @classmethod
    def _add_ram_attribute_line(cls):
        cls.computer_ram_attribute_lines = cls.env[
            "product.template.attribute.line"
        ].create(cls.COMPUTER_HDD_PTAL_VALUES)

        cls._setup_ram_attribute_line()

    @classmethod
    def _setup_ram_attribute_line(cls):

        cls.computer_ram_attribute_lines.product_template_value_ids[0].price_extra = 20
        cls.computer_ram_attribute_lines.product_template_value_ids[1].price_extra = 40
        cls.computer_ram_attribute_lines.product_template_value_ids[2].price_extra = 80

    @classmethod
    def _add_ssd_attribute_line(cls):
        cls.computer_ssd_attribute_lines = cls.env[
            "product.template.attribute.line"
        ].create(cls.COMPUTER_SSD_PTAL_VALUES)

        cls._setup_ssd_attribute_line()

    @classmethod
    def _setup_ssd_attribute_line(cls):

        cls.computer_ssd_attribute_lines.product_template_value_ids[0].price_extra = 200
        cls.computer_ssd_attribute_lines.product_template_value_ids[1].price_extra = 400

    @classmethod
    def _add_hdd_attribute_line(cls):
        cls.computer_hdd_attribute_lines = cls.env[
            "product.template.attribute.line"
        ].create(cls.COMPUTER_HDD_PTAL_VALUES)

        cls._setup_hdd_attribute_line()

    @classmethod
    def _setup_hdd_attribute_line(cls):

        cls.computer_hdd_attribute_lines.product_template_value_ids[0].price_extra = 2
        cls.computer_hdd_attribute_lines.product_template_value_ids[1].price_extra = 4
        cls.computer_hdd_attribute_lines.product_template_value_ids[2].price_extra = 8

    def _add_ram_exclude_for(self):
        self._get_product_value_id(
            self.computer_ram_attribute_lines, self.ram_16
        ).update(
            {
                "exclude_for": [
                    Command.create(
                        {
                            "product_tmpl_id": self.computer.id,
                            "value_ids": [
                                Command.set(
                                    [
                                        self._get_product_value_id(
                                            self.computer_hdd_attribute_lines,
                                            self.hdd_1,
                                        ).id
                                    ]
                                )
                            ],
                        }
                    )
                ]
            }
        )

    def _get_product_value_id(
        self, product_template_attribute_lines, product_attribute_value
    ):
        return product_template_attribute_lines.product_template_value_ids.filtered(
            lambda product_value_id: (
                product_value_id.product_attribute_value_id == product_attribute_value
            )
        )[0]

    def _get_product_template_attribute_value(
        self, product_attribute_value, model=False
    ):
        if not model:
            model = self.computer
        return model.valid_product_template_attribute_line_ids.filtered(
            lambda l: l.attribute_id == product_attribute_value.attribute_id
        ).product_template_value_ids.filtered(
            lambda v: v.product_attribute_value_id == product_attribute_value
        )

    def _add_exclude(self, m1, m2, product_template=False):
        m1.update(
            {
                "exclude_for": [
                    (
                        0,
                        0,
                        {
                            "product_tmpl_id": (product_template or self.computer).id,
                            "value_ids": [(6, 0, [m2.id])],
                        },
                    )
                ]
            }
        )


@tagged("post_install", "-at_install")
class TestProductAttributeValueConfig(TestProductAttributeValueCommon):
    def test_product_template_attribute_values_creation(self):
        self.assertEqual(
            len(self.computer_ssd_attribute_lines.product_template_value_ids),
            2,
            "Product attribute values (ssd) were not automatically created",
        )
        self.assertEqual(
            len(self.computer_ram_attribute_lines.product_template_value_ids),
            3,
            "Product attribute values (ram) were not automatically created",
        )
        self.assertEqual(
            len(self.computer_hdd_attribute_lines.product_template_value_ids),
            3,
            "Product attribute values (hdd) were not automatically created",
        )
        self.assertEqual(
            len(self.computer_case_size_attribute_lines.product_template_value_ids),
            3,
            "Product attribute values (size) were not automatically created",
        )

    def test_complete_inverse_exclusions_symmetry(self):
        Attribute = self.env["product.attribute"]
        color, size, material = Attribute.create(
            [
                {
                    "name": "Excl Color",
                    "sequence": 1,
                    "create_variant": "no_variant",
                    "value_ids": [
                        Command.create({"name": "Red"}),
                        Command.create({"name": "Blue"}),
                    ],
                },
                {
                    "name": "Excl Size",
                    "sequence": 2,
                    "create_variant": "no_variant",
                    "value_ids": [
                        Command.create({"name": "S"}),
                        Command.create({"name": "M"}),
                    ],
                },
                {
                    "name": "Excl Material",
                    "sequence": 3,
                    "create_variant": "no_variant",
                    "value_ids": [
                        Command.create({"name": "Cotton"}),
                        Command.create({"name": "Wool"}),
                    ],
                },
            ]
        )
        tmpl = self.env["product.template"].create(
            {
                "name": "Exclusion Symmetry",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": a.id,
                            "value_ids": [Command.set(a.value_ids.ids)],
                        }
                    )
                    for a in (color, size, material)
                ],
            }
        )

        def ptav(attribute_value):
            return tmpl.valid_product_template_attribute_line_ids.product_template_value_ids.filtered(
                lambda p: p.product_attribute_value_id == attribute_value
            )

        red = ptav(color.value_ids[0])
        s = ptav(size.value_ids[0])
        cotton = ptav(material.value_ids[0])
        s.write(
            {
                "exclude_for": [
                    Command.create(
                        {
                            "product_tmpl_id": tmpl.id,
                            "value_ids": [Command.set((red + cotton).ids)],
                        }
                    )
                ]
            }
        )

        exclusions = tmpl._get_attribute_exclusions()["exclusions"]
        for value_id, excluded_ids in exclusions.items():
            for excluded_id in excluded_ids:
                self.assertIn(
                    value_id,
                    exclusions[excluded_id],
                    "exclusion %s->%s is not mirrored back" % (value_id, excluded_id),
                )
        self.assertIn(red.id, exclusions[s.id], "S must exclude Red")
        self.assertIn(cotton.id, exclusions[s.id], "S must exclude Cotton")
        self.assertIn(s.id, exclusions[red.id], "Red must exclude S")

    def test_get_variant_for_combination(self):
        computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
        computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
        computer_ram_16 = self._get_product_template_attribute_value(self.ram_16)
        computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)

        combination = computer_ssd_256 + computer_ram_8 + computer_hdd_1
        ok_variant = self.computer._get_variant_for_combination(combination)
        self.assertEqual(ok_variant.product_template_attribute_value_ids, combination)

        combination = (
            computer_ssd_256 + computer_ram_8 + computer_ram_16 + computer_hdd_1
        )
        variant = self.computer._get_variant_for_combination(combination)
        self.assertEqual(len(variant), 0)

        combination = computer_ssd_256 + computer_ram_8
        variant = self.computer._get_variant_for_combination(combination)
        self.assertFalse(variant)

    @mute_logger("odoo.models.unlink")
    def test_product_filtered_exclude_for(self):
        computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
        computer_ssd_512 = self._get_product_template_attribute_value(self.ssd_512)
        computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
        computer_ram_16 = self._get_product_template_attribute_value(self.ram_16)
        computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)

        self.assertEqual(len(self.computer._get_possible_variants()), 18)
        self._add_ram_exclude_for()
        self.assertEqual(len(self.computer._get_possible_variants()), 16)
        self.assertTrue(
            self.computer._get_variant_for_combination(
                computer_ssd_256 + computer_ram_8 + computer_hdd_1
            )._is_variant_possible()
        )
        self.assertFalse(
            self.computer._get_variant_for_combination(
                computer_ssd_256 + computer_ram_16 + computer_hdd_1
            )
        )
        self.assertFalse(
            self.computer._get_variant_for_combination(
                computer_ssd_512 + computer_ram_16 + computer_hdd_1
            )
        )

    def test_children_product_filtered_exclude_for(self):
        computer_hdd_4 = self._get_product_template_attribute_value(self.hdd_4)
        computer_size_m = self._get_product_template_attribute_value(
            self.size_m, self.computer_case
        )
        self._add_exclude(computer_hdd_4, computer_size_m, self.computer_case)
        self.assertEqual(
            len(self.computer_case._get_possible_variants(computer_hdd_4)), 2
        )
        self.assertFalse(
            self.computer_case._get_variant_for_combination(
                computer_size_m
            )._is_variant_possible(computer_hdd_4)
        )

    @mute_logger("odoo.models.unlink")
    def test_is_combination_possible(self):
        computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
        computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
        computer_ram_16 = self._get_product_template_attribute_value(self.ram_16)
        computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)
        self._add_exclude(computer_ram_16, computer_hdd_1)

        self.assertTrue(
            self.computer._is_combination_possible(
                computer_ssd_256 + computer_ram_8 + computer_hdd_1
            )
        )

        self.assertFalse(
            self.computer._is_combination_possible(
                computer_ssd_256 + computer_ram_16 + computer_hdd_1
            )
        )

        self.assertFalse(
            self.computer._is_combination_possible(computer_ssd_256 + computer_ram_16)
        )

        mouse = self.env["product.template"].create({"name": "Mouse"})
        self.assertTrue(
            mouse._is_combination_possible(self.env["product.template.attribute.value"])
        )

        color_attribute = self.env["product.attribute"].create({"name": "Color"})
        color_red = self.env["product.attribute.value"].create(
            {
                "name": "Red",
                "attribute_id": color_attribute.id,
            }
        )
        color_green = self.env["product.attribute.value"].create(
            {
                "name": "Green",
                "attribute_id": color_attribute.id,
            }
        )
        self.env["product.template.attribute.line"].create(
            {
                "product_tmpl_id": mouse.id,
                "attribute_id": color_attribute.id,
                "value_ids": [(6, 0, [color_red.id, color_green.id])],
            }
        )

        mouse_color_red = self._get_product_template_attribute_value(color_red, mouse)
        mouse_color_green = self._get_product_template_attribute_value(
            color_green, mouse
        )

        self._add_exclude(computer_ssd_256, mouse_color_green, mouse)

        variant = self.computer._get_variant_for_combination(
            computer_ssd_256 + computer_ram_8 + computer_hdd_1
        )

        self.assertFalse(
            self.computer._is_combination_possible(
                computer_ssd_256 + computer_ram_16 + mouse_color_red
            )
        )

        self.assertTrue(
            self.computer._is_combination_possible(
                computer_ssd_256 + computer_ram_8 + computer_hdd_1, mouse_color_red
            )
        )
        self.assertTrue(
            mouse._is_combination_possible(
                mouse_color_red, computer_ssd_256 + computer_ram_8 + computer_hdd_1
            )
        )

        self.assertTrue(
            self.computer._is_combination_possible(
                computer_ssd_256 + computer_ram_8 + computer_hdd_1, mouse_color_green
            )
        )

        self.assertFalse(
            mouse._is_combination_possible(
                mouse_color_green, computer_ssd_256 + computer_ram_8 + computer_hdd_1
            )
        )

        variant.unlink()
        self.assertFalse(
            self.computer._is_combination_possible(
                computer_ssd_256 + computer_ram_8 + computer_hdd_1
            )
        )

        combination = computer_ssd_256 + computer_ram_8 + computer_hdd_1
        self.env["product.product"].create(
            {
                "product_tmpl_id": self.computer.id,
                "product_template_attribute_value_ids": [(6, 0, combination.ids)],
                "active": False,
            }
        )
        self.env["product.product"].create(
            {
                "product_tmpl_id": self.computer.id,
                "product_template_attribute_value_ids": [(6, 0, combination.ids)],
                "active": True,
            }
        )
        self.assertTrue(
            self.computer._is_combination_possible(
                computer_ssd_256 + computer_ram_8 + computer_hdd_1
            )
        )

    @mute_logger("odoo.models.unlink")
    def test_get_first_possible_combination(self):
        computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
        computer_ssd_512 = self._get_product_template_attribute_value(self.ssd_512)
        computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
        computer_ram_16 = self._get_product_template_attribute_value(self.ram_16)
        computer_ram_32 = self._get_product_template_attribute_value(self.ram_32)
        computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)
        computer_hdd_2 = self._get_product_template_attribute_value(self.hdd_2)
        computer_hdd_4 = self._get_product_template_attribute_value(self.hdd_4)
        self._add_exclude(computer_ram_16, computer_hdd_1)

        gen = self.computer._get_possible_combinations()
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_8 + computer_hdd_1)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_8 + computer_hdd_2)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_8 + computer_hdd_4)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_16 + computer_hdd_2)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_16 + computer_hdd_4)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_32 + computer_hdd_1)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_32 + computer_hdd_2)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_32 + computer_hdd_4)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_8 + computer_hdd_1)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_8 + computer_hdd_2)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_8 + computer_hdd_4)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_16 + computer_hdd_2)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_16 + computer_hdd_4)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_32 + computer_hdd_1)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_32 + computer_hdd_2)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_32 + computer_hdd_4)
        self.assertIsNone(next(gen, None))

        computer_ram_16.product_attribute_value_id.sequence = -1
        self.assertEqual(
            self.computer._get_first_possible_combination(),
            computer_ssd_256 + computer_ram_16 + computer_hdd_2,
        )

        self.ram_attribute.sequence = 10
        self.assertEqual(
            self.computer._get_first_possible_combination(),
            computer_ssd_256 + computer_ram_8 + computer_hdd_1,
        )

        self.ram_attribute.sequence = 2
        computer_ram_16.product_attribute_value_id.sequence = 2
        computer_ram_32.product_attribute_value_id.sequence = -1
        self.assertEqual(
            self.computer._get_first_possible_combination(),
            computer_ssd_256 + computer_ram_32 + computer_hdd_1,
        )

        computer_ram_32.product_attribute_value_id.sequence = 3
        computer_ram_16.product_attribute_value_id.sequence = -1
        self._add_exclude(computer_ram_16, computer_hdd_2)
        self._add_exclude(computer_ram_16, computer_hdd_4)
        self.assertEqual(
            self.computer._get_first_possible_combination(),
            computer_ssd_256 + computer_ram_8 + computer_hdd_1,
        )

        computer_ram_16.product_attribute_value_id.sequence = 2
        self._add_exclude(computer_ram_8, computer_hdd_1)
        self._add_exclude(computer_ram_8, computer_hdd_2)
        self._add_exclude(computer_ram_8, computer_hdd_4)
        self._add_exclude(computer_ram_32, computer_hdd_1)
        self._add_exclude(computer_ram_32, computer_hdd_2)
        self._add_exclude(computer_ram_32, computer_ssd_256)
        self.assertEqual(
            self.computer._get_first_possible_combination(),
            computer_ssd_512 + computer_ram_32 + computer_hdd_4,
        )

        with self.assertRaises(UserError):
            self._add_exclude(computer_ram_32, computer_hdd_4)

        for exclusion in computer_ram_32.exclude_for:
            computer_ram_32.write({"exclude_for": [(2, exclusion.id, 0)]})

        computer_ram_32.write(
            {
                "exclude_for": [
                    (
                        0,
                        computer_ram_32.exclude_for.id,
                        {
                            "product_tmpl_id": self.computer.id,
                            "value_ids": [
                                (
                                    6,
                                    0,
                                    [
                                        computer_hdd_1.id,
                                        computer_hdd_2.id,
                                        computer_hdd_4.id,
                                        computer_ssd_256.id,
                                        computer_ssd_512.id,
                                    ],
                                )
                            ],
                        },
                    )
                ]
            }
        )

        self.assertEqual(
            self.computer._get_first_possible_combination(),
            self.env["product.template.attribute.value"],
        )
        gen = self.computer._get_possible_combinations()
        self.assertIsNone(next(gen, None))

        mouse = self.env["product.template"].create({"name": "Mouse"})
        self.assertTrue(
            mouse._is_combination_possible(self.env["product.template.attribute.value"])
        )

        color_attribute = self.env["product.attribute"].create({"name": "Color"})
        color_red = self.env["product.attribute.value"].create(
            {
                "name": "Red",
                "attribute_id": color_attribute.id,
            }
        )
        color_green = self.env["product.attribute.value"].create(
            {
                "name": "Green",
                "attribute_id": color_attribute.id,
            }
        )
        self.env["product.template.attribute.line"].create(
            {
                "product_tmpl_id": mouse.id,
                "attribute_id": color_attribute.id,
                "value_ids": [(6, 0, [color_red.id, color_green.id])],
            }
        )

        mouse_color_red = self._get_product_template_attribute_value(color_red, mouse)
        mouse_color_green = self._get_product_template_attribute_value(
            color_green, mouse
        )

        self._add_exclude(computer_ssd_256, mouse_color_red, mouse)
        self.assertEqual(
            mouse._get_first_possible_combination(
                parent_combination=computer_ssd_256 + computer_ram_8 + computer_hdd_1
            ),
            mouse_color_green,
        )

        color_blue = self.env["product.attribute.value"].create(
            {
                "name": "Blue",
                "attribute_id": color_attribute.id,
            }
        )
        color_yellow = self.env["product.attribute.value"].create(
            {
                "name": "Yellow",
                "attribute_id": color_attribute.id,
            }
        )
        self.env["product.template.attribute.line"].create(
            {
                "product_tmpl_id": mouse.id,
                "attribute_id": color_attribute.id,
                "value_ids": [(6, 0, [color_blue.id, color_yellow.id])],
            }
        )
        mouse_color_yellow = self._get_product_template_attribute_value(
            color_yellow, mouse
        )
        self.assertEqual(
            mouse._get_first_possible_combination(necessary_values=mouse_color_yellow),
            mouse_color_red + mouse_color_yellow,
        )

        product_template = self.env["product.template"].create(
            {
                "name": "many combinations",
            }
        )

        for i in range(10):
            product_attribute = self.env["product.attribute"].create(
                {
                    "name": "att %s" % i,
                    "create_variant": "dynamic",
                    "sequence": i,
                }
            )

            for j in range(50):
                value = self.env["product.attribute.value"].create(
                    [
                        {
                            "name": "val %s" % j,
                            "attribute_id": product_attribute.id,
                            "sequence": j,
                        }
                    ]
                )

            self.env["product.template.attribute.line"].create(
                [
                    {
                        "attribute_id": product_attribute.id,
                        "product_tmpl_id": product_template.id,
                        "value_ids": [(6, 0, product_attribute.value_ids.ids)],
                    }
                ]
            )

        self._add_exclude(
            self._get_product_template_attribute_value(
                product_template.attribute_line_ids[1].value_ids[0],
                model=product_template,
            ),
            self._get_product_template_attribute_value(
                product_template.attribute_line_ids[0].value_ids[0],
                model=product_template,
            ),
            product_template,
        )
        self._add_exclude(
            self._get_product_template_attribute_value(
                product_template.attribute_line_ids[0].value_ids[0],
                model=product_template,
            ),
            self._get_product_template_attribute_value(
                product_template.attribute_line_ids[1].value_ids[1],
                model=product_template,
            ),
            product_template,
        )

        combination = self.env["product.template.attribute.value"]
        for idx, ptal in enumerate(product_template.attribute_line_ids):
            if idx != 1:
                value = ptal.product_template_value_ids[0]
            else:
                value = ptal.product_template_value_ids[2]
            combination += value

        started_at = time.time()
        self.assertEqual(
            product_template._get_first_possible_combination(), combination
        )
        elapsed = time.time() - started_at
        self.assertLess(elapsed, 0.5)

    @mute_logger("odoo.models.unlink")
    def test_get_closest_possible_combinations(self):
        computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
        computer_ssd_512 = self._get_product_template_attribute_value(self.ssd_512)
        computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
        computer_ram_16 = self._get_product_template_attribute_value(self.ram_16)
        computer_ram_32 = self._get_product_template_attribute_value(self.ram_32)
        computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)
        computer_hdd_2 = self._get_product_template_attribute_value(self.hdd_2)
        computer_hdd_4 = self._get_product_template_attribute_value(self.hdd_4)
        self._add_exclude(computer_ram_16, computer_hdd_1)

        gen = self.computer._get_closest_possible_combinations(None)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_8 + computer_hdd_1)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_8 + computer_hdd_2)

        gen = self.computer._get_closest_possible_combinations(computer_hdd_1)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_8 + computer_hdd_1)
        self.assertEqual(next(gen), computer_ssd_256 + computer_ram_32 + computer_hdd_1)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_8 + computer_hdd_1)
        self.assertEqual(next(gen), computer_ssd_512 + computer_ram_32 + computer_hdd_1)
        self.assertIsNone(next(gen, None))

        self.assertEqual(
            self.computer._get_closest_possible_combination(computer_hdd_2),
            computer_ssd_256 + computer_ram_8 + computer_hdd_2,
        )

        self.assertEqual(
            self.computer._get_closest_possible_combination(
                computer_hdd_2 + computer_ram_16
            ),
            computer_ssd_256 + computer_ram_16 + computer_hdd_2,
        )

        self.assertEqual(
            self.computer._get_closest_possible_combination(
                computer_hdd_1 + computer_ram_16
            ),
            computer_ssd_256 + computer_ram_8 + computer_hdd_1,
        )

        self.assertEqual(
            self.computer._get_closest_possible_combination(
                computer_ssd_256 + computer_ram_8 + computer_hdd_4 + computer_hdd_2
            ),
            computer_ssd_256 + computer_ram_8 + computer_hdd_4,
        )

        product_template = self.env["product.template"].create(
            {
                "name": "many combinations",
            }
        )

        for i in range(10):
            product_attribute = self.env["product.attribute"].create(
                {
                    "name": "att %s" % i,
                    "create_variant": "dynamic",
                    "sequence": i,
                }
            )

            for j in range(10):
                self.env["product.attribute.value"].create(
                    [
                        {
                            "name": "val %s/%s" % (i, j),
                            "attribute_id": product_attribute.id,
                            "sequence": j,
                        }
                    ]
                )

            self.env["product.template.attribute.line"].create(
                [
                    {
                        "attribute_id": product_attribute.id,
                        "product_tmpl_id": product_template.id,
                        "value_ids": [(6, 0, product_attribute.value_ids.ids)],
                    }
                ]
            )

        combination = self.env["product.template.attribute.value"]
        for ptal in product_template.attribute_line_ids:
            combination += ptal.product_template_value_ids[5]

        started_at = time.time()
        self.assertEqual(
            product_template._get_closest_possible_combination(combination), combination
        )
        elapsed = time.time() - started_at
        self.assertLess(elapsed, 0.5)

    @mute_logger("odoo.models.unlink")
    def test_clear_caches(self):
        computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
        computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
        computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)
        combination = computer_ssd_256 + computer_ram_8 + computer_hdd_1

        variant = self.computer._get_variant_for_combination(combination)
        self.assertTrue(variant)

        variant.unlink()
        self.assertFalse(self.computer._get_variant_for_combination(combination))

        variant = self.env["product.product"].create(
            {
                "product_tmpl_id": self.computer.id,
                "product_template_attribute_value_ids": [(6, 0, combination.ids)],
            }
        )
        self.assertEqual(
            variant, self.computer._get_variant_for_combination(combination)
        )

        variant.product_template_attribute_value_ids = False
        self.assertFalse(self.computer._get_variant_id_for_combination(combination))

    def test_constraints(self):
        with self.assertRaises(
            UserError,
            msg="can't change variants creation mode of attribute used on product",
        ):
            self.ram_attribute.create_variant = "no_variant"

        with self.assertRaises(UserError, msg="can't delete attribute used on product"):
            self.ram_attribute.unlink()

        with self.assertRaises(
            UserError, msg="can't change the attribute of an value used on product"
        ):
            self.ram_32.attribute_id = self.hdd_attribute.id

        with self.assertRaises(UserError, msg="can't delete value used on product"):
            self.ram_32.unlink()

        with self.assertRaises(
            ValidationError, msg="can't have attribute without value on product"
        ):
            self.env["product.template.attribute.line"].create(
                {
                    "product_tmpl_id": self.computer_case.id,
                    "attribute_id": self.hdd_attribute.id,
                    "value_ids": [(6, 0, [])],
                }
            )

        with self.assertRaises(
            ValidationError, msg="value attribute must match line attribute"
        ):
            self.env["product.template.attribute.line"].create(
                {
                    "product_tmpl_id": self.computer_case.id,
                    "attribute_id": self.ram_attribute.id,
                    "value_ids": [(6, 0, [self.ssd_256.id])],
                }
            )

        with self.assertRaises(
            UserError, msg="can't change the attribute of an attribute line"
        ):
            self.computer_ssd_attribute_lines.attribute_id = self.hdd_attribute.id

        with self.assertRaises(
            UserError, msg="can't change the product of an attribute line"
        ):
            self.computer_ssd_attribute_lines.product_tmpl_id = self.computer_case.id

        with self.assertRaises(
            UserError,
            msg="can't change the value of a product template attribute value",
        ):
            self.computer_ram_attribute_lines.product_template_value_ids[
                0
            ].product_attribute_value_id = self.hdd_1

        with self.assertRaises(
            UserError,
            msg="can't change the product of a product template attribute value",
        ):
            self.computer_ram_attribute_lines.product_template_value_ids[
                0
            ].product_tmpl_id = self.computer_case.id

    @mute_logger("odoo.models.unlink")
    def test_inactive_related_product_update(self):
        product_attribut = self.env["product.attribute"].create(
            {
                "name": "PA",
                "sequence": 1,
                "create_variant": "no_variant",
            }
        )
        a1 = self.env["product.attribute.value"].create(
            {
                "name": "pa_value",
                "attribute_id": product_attribut.id,
                "sequence": 1,
            }
        )
        product = self.env["product.template"].create(
            {
                "name": "P1",
                "type": "consu",
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": product_attribut.id,
                            "value_ids": [(6, 0, [a1.id])],
                        },
                    )
                ],
            }
        )
        self.assertEqual(
            product_attribut.count_product_tmpl,
            1,
            "The product attribute must have an associated product",
        )
        product.action_archive()
        self.assertFalse(product.active, "The product should be archived.")
        product.write({"attribute_line_ids": [[5, 0, 0]]})
        product.action_unarchive()
        self.assertTrue(product.active, "The product should be unarchived.")
        self.assertEqual(
            product_attribut.count_product_tmpl,
            0,
            "The product attribute must not have an associated product",
        )

    def test_copy_extra_prices_of_product_attribute_values(self):
        product_template = self.computer
        extra_prices = (
            product_template.attribute_line_ids.product_template_value_ids.mapped(
                "price_extra"
            )
        )
        copied_template = product_template.copy()
        copied_extra_prices = (
            copied_template.attribute_line_ids.product_template_value_ids.mapped(
                "price_extra"
            )
        )
        self.assertEqual(extra_prices, copied_extra_prices)

    def test_04_create_product_variant_non_dynamic(self):
        computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
        computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
        computer_ram_16 = self._get_product_template_attribute_value(self.ram_16)
        computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)
        self._add_exclude(computer_ram_16, computer_hdd_1)

        combination = computer_ssd_256 + computer_ram_8 + computer_hdd_1
        variant1 = self.computer._get_variant_for_combination(combination)
        self.assertEqual(self.computer._create_product_variant(combination), variant1)

        Product = self.env["product.product"]
        variant1.unlink()
        self.assertEqual(self.computer._create_product_variant(combination), Product)

    def test_05_create_product_variant_dynamic(self):
        self.computer_hdd_attribute_lines.write({"active": False})
        self.hdd_attribute.create_variant = "dynamic"
        self._add_hdd_attribute_line()

        computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
        computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
        computer_ram_16 = self._get_product_template_attribute_value(self.ram_16)
        computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)
        self._add_exclude(computer_ram_16, computer_hdd_1)

        impossible_combination = computer_ssd_256 + computer_ram_16 + computer_hdd_1
        Product = self.env["product.product"]
        self.assertEqual(
            self.computer._create_product_variant(impossible_combination), Product
        )

        combination = computer_ssd_256 + computer_ram_8 + computer_hdd_1
        variant = self.computer._create_product_variant(combination)
        self.assertTrue(variant)

        self.assertEqual(variant, self.computer._create_product_variant(combination))
