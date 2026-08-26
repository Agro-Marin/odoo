import itertools
import random

from odoo import Command
from odoo.tools import mute_logger

from .common import ProductVariantsCommon


class TestCombinationEngineHardening(ProductVariantsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sofa_red = cls.product_template_sofa.valid_product_template_attribute_line_ids.product_template_value_ids.filtered(
            lambda ptav: ptav.product_attribute_value_id == cls.color_attribute_red
        )
        cls.child = cls.env["product.template"].create({"name": "Child"})
        cls.env["product.template.attribute.line"].create(
            {
                "product_tmpl_id": cls.child.id,
                "attribute_id": cls.size_attribute.id,
                "value_ids": [
                    Command.set(
                        [
                            cls.size_attribute_s.id,
                            cls.size_attribute_m.id,
                            cls.size_attribute_l.id,
                        ]
                    )
                ],
            }
        )
        ptavs = cls.child.valid_product_template_attribute_line_ids.product_template_value_ids
        cls.child_s = ptavs.filtered(
            lambda v: v.product_attribute_value_id == cls.size_attribute_s
        )
        cls.child_m = ptavs.filtered(
            lambda v: v.product_attribute_value_id == cls.size_attribute_m
        )
        cls.child_l = ptavs.filtered(
            lambda v: v.product_attribute_value_id == cls.size_attribute_l
        )

    def _add_parent_exclusion(self, excluded_ptavs):
        return self.env["product.template.attribute.exclusion"].create(
            {
                "product_tmpl_id": self.child.id,
                "product_template_attribute_value_id": self.sofa_red.id,
                "value_ids": [Command.set(excluded_ptavs.ids)],
            }
        )

    def test_cartesian_product_prunes_parent_exclusions(self):
        self._add_parent_exclusion(self.child_s + self.child_m)
        per_line = [
            self.child.valid_product_template_attribute_line_ids.product_template_value_ids
        ]

        combos = list(self.child._cartesian_product(per_line, self.sofa_red))

        self.assertEqual(
            len(combos), 1, "only the non-excluded value should be yielded"
        )
        self.assertEqual(combos[0], self.child_l)

    def test_possible_combinations_respect_parent_exclusions(self):
        self._add_parent_exclusion(self.child_s + self.child_m)

        combos = list(
            self.child._get_possible_combinations(parent_combination=self.sofa_red)
        )

        self.assertTrue(combos, "at least the non-excluded combination is possible")
        for combo in combos:
            self.assertNotIn(self.child_s, combo)
            self.assertNotIn(self.child_m, combo)
        self.assertTrue(any(self.child_l in combo for combo in combos))

    def test_cartesian_product_without_exclusions_is_full_product(self):
        per_line = [
            self.child.valid_product_template_attribute_line_ids.product_template_value_ids
        ]
        empty_parent = self.env["product.template.attribute.value"]

        combos = list(self.child._cartesian_product(per_line, empty_parent))

        self.assertEqual(len(combos), 3)
        yielded = self.env["product.template.attribute.value"].union(*combos)
        self.assertEqual(yielded, self.child_s + self.child_m + self.child_l)

    @mute_logger("odoo.models.unlink")
    def test_batch_reactivation_regenerates_variants_per_record(self):
        Template = self.env["product.template"]
        active_tmpl = Template.create({"name": "StaysActive"})
        archived_tmpl = Template.create({"name": "GetsArchived"})
        archived_tmpl.write({"active": False})
        self.assertFalse(
            archived_tmpl.with_context(active_test=False).product_variant_ids.active
        )

        (active_tmpl + archived_tmpl).write({"active": True})

        self.assertTrue(
            archived_tmpl.product_variant_ids,
            "every reactivated template must end up with an active variant",
        )

    def _oracle(self, per_line, own_excl, parent_excluded):
        if not per_line:
            return set()
        non_empty = [line for line in per_line if line]
        if not non_empty:
            return {frozenset()}
        expected = set()
        for combo_ids in itertools.product(*[line.ids for line in non_empty]):
            combo = set(combo_ids)
            if combo & parent_excluded:
                continue
            if any(own_excl.get(a, set()) & (combo - {a}) for a in combo):
                continue
            expected.add(frozenset(combo))
        return expected

    def _assert_engine_matches_oracle(self, tmpl, per_line, parent_combination, msg=""):
        own_excl = {k: set(v) for k, v in tmpl._get_own_attribute_exclusions().items()}
        parent_excluded = {
            excluded_id
            for excluded_ids in tmpl._get_parent_attribute_exclusions(
                parent_combination
            ).values()
            for excluded_id in excluded_ids
        }
        yielded = list(tmpl._cartesian_product(per_line, parent_combination))
        got = {frozenset(combo.ids) for combo in yielded}
        self.assertEqual(
            len(yielded), len(got), "engine yielded duplicate combinations: %s" % msg
        )
        self.assertEqual(got, self._oracle(per_line, own_excl, parent_excluded), msg)

    def _build_random_template(self, rng):
        Attribute = self.env["product.attribute"]
        attributes = Attribute.create(
            [
                {
                    "name": "Attr%d" % i,
                    "sequence": i,
                    "create_variant": "no_variant",
                    "value_ids": [
                        Command.create({"name": "v%d_%d" % (i, j)})
                        for j in range(rng.randint(1, 3))
                    ],
                }
                for i in range(rng.randint(2, 4))
            ]
        )
        return self.env["product.template"].create(
            {
                "name": "Rand",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": a.id,
                            "value_ids": [Command.set(a.value_ids.ids)],
                        }
                    )
                    for a in attributes
                ],
            }
        )

    @mute_logger("odoo.models.unlink")
    def test_cartesian_product_matches_bruteforce_oracle(self):
        PTAV = self.env["product.template.attribute.value"]
        Exclusion = self.env["product.template.attribute.exclusion"]
        Attribute = self.env["product.attribute"]
        for seed in range(30):
            rng = random.Random(seed)
            tmpl = self._build_random_template(rng)
            line_ptavs = [
                line.product_template_value_ids
                for line in tmpl.valid_product_template_attribute_line_ids
            ]

            for _ in range(rng.randint(0, 3)):
                la, lb = rng.sample(range(len(line_ptavs)), 2)
                Exclusion.create(
                    {
                        "product_tmpl_id": tmpl.id,
                        "product_template_attribute_value_id": rng.choice(
                            line_ptavs[la]
                        ).id,
                        "value_ids": [Command.set(rng.choice(line_ptavs[lb]).ids)],
                    }
                )

            per_line = list(line_ptavs)
            if rng.random() < 0.3:
                idx = rng.randrange(len(per_line))
                if len(per_line[idx]) > 1:
                    per_line[idx] = per_line[idx][1:]
            if rng.random() < 0.2:
                per_line[rng.randrange(len(per_line))] = PTAV

            parent = PTAV
            if rng.random() < 0.4:
                parent_attr = Attribute.create(
                    {
                        "name": "Parent",
                        "create_variant": "no_variant",
                        "value_ids": [Command.create({"name": "p"})],
                    }
                )
                parent_tmpl = self.env["product.template"].create(
                    {
                        "name": "ParentTmpl",
                        "attribute_line_ids": [
                            Command.create(
                                {
                                    "attribute_id": parent_attr.id,
                                    "value_ids": [
                                        Command.set(parent_attr.value_ids.ids)
                                    ],
                                }
                            )
                        ],
                    }
                )
                parent = parent_tmpl.valid_product_template_attribute_line_ids.product_template_value_ids
                all_ptavs = list(
                    tmpl.valid_product_template_attribute_line_ids.product_template_value_ids
                )
                victims = rng.sample(all_ptavs, rng.randint(1, min(2, len(all_ptavs))))
                Exclusion.create(
                    {
                        "product_tmpl_id": tmpl.id,
                        "product_template_attribute_value_id": parent.id,
                        "value_ids": [Command.set([v.id for v in victims])],
                    }
                )

            self._assert_engine_matches_oracle(
                tmpl, per_line, parent, msg="seed=%d" % seed
            )

    def test_cartesian_product_empty_list_yields_nothing(self):
        self.assertEqual(
            list(
                self.child._cartesian_product(
                    [], self.env["product.template.attribute.value"]
                )
            ),
            [],
        )

    def test_cartesian_product_all_empty_lines_yields_empty_combination(self):
        PTAV = self.env["product.template.attribute.value"]
        combos = list(self.child._cartesian_product([PTAV, PTAV], PTAV))
        self.assertEqual(combos, [PTAV])

    def test_cartesian_product_fully_excluded_line_yields_nothing(self):
        self._add_parent_exclusion(self.child_s + self.child_m + self.child_l)
        per_line = [
            self.child.valid_product_template_attribute_line_ids.product_template_value_ids
        ]
        self.assertEqual(
            list(self.child._cartesian_product(per_line, self.sofa_red)), []
        )

    def test_document_count_counts_active_variant_documents(self):
        tmpl = self.env["product.template"].create({"name": "WithDocs"})
        variant = tmpl.product_variant_ids
        self.env["product.document"].create(
            {"name": "spec", "res_model": "product.product", "res_id": variant.id}
        )
        tmpl.invalidate_recordset(["product_document_count"])
        self.assertEqual(tmpl.product_document_count, 1)

        variant.write({"active": False})
        tmpl.invalidate_recordset(["product_document_count"])
        self.assertEqual(
            tmpl.product_document_count,
            0,
            "documents on archived variants are not counted",
        )
