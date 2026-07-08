# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression coverage for the variant-combination engine on product.template.

Pins the contract of `_cartesian_product` / `_get_possible_combinations` so the
engine can be refactored safely, and locks in the correctness fixes referenced in
each test's docstring.
"""

import itertools
import random

from odoo import Command
from odoo.tools import mute_logger

from .common import ProductVariantsCommon


class TestCombinationEngineHardening(ProductVariantsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # `product_template_sofa` (Color: red/blue/green) plays the parent; a
        # separate `child` template (Size: S/M/L) plays the optional product.
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
        """Exclude ``excluded_ptavs`` on ``child`` whenever the parent is Red."""
        return self.env["product.template.attribute.exclusion"].create(
            {
                "product_tmpl_id": self.child.id,
                "product_template_attribute_value_id": self.sofa_red.id,
                "value_ids": [Command.set(excluded_ptavs.ids)],
            }
        )

    def test_cartesian_product_prunes_parent_exclusions(self):
        """A1: `_cartesian_product` must early-prune parent-excluded values.

        `_get_parent_attribute_exclusions` returns {parent_ptav: [excluded]}. The
        seeding loop previously iterated the dict *keys* (parent ptavs, disjoint
        from the child's values), making the pruning a silent no-op. This is a
        white-box guard: the black-box result stays correct either way because
        `_is_combination_possible` re-filters, so only this level catches it.
        """
        self._add_parent_exclusion(self.child_s + self.child_m)
        per_line = [
            self.child.valid_product_template_attribute_line_ids.product_template_value_ids
        ]

        combos = list(self.child._cartesian_product(per_line, self.sofa_red))

        # S and M are excluded by the parent → must not be yielded at all.
        self.assertEqual(
            len(combos), 1, "only the non-excluded value should be yielded"
        )
        self.assertEqual(combos[0], self.child_l)

    def test_possible_combinations_respect_parent_exclusions(self):
        """A1 (black-box): possible combinations never contain parent-excluded values."""
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
        """Baseline contract: with no exclusion, every value is yielded."""
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
        """A2: reactivating a mixed batch must regenerate variants for every template.

        The gate used the batch-union `len(self.product_variant_ids) == 0`; a single
        template that still had active variants masked the archived ones, leaving
        them reactivated but variant-less.
        """
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

    # === CHARACTERIZATION: `_cartesian_product` vs a brute-force oracle ===
    #
    # `_cartesian_product` is a hand-rolled backtracking state machine that prunes
    # invalid partial combinations early (for performance). These tests pin its
    # *observable* contract against the naive `itertools.product` + filter it
    # optimizes, so the engine can later be reworked and proven equivalent. Scope:
    # they trust the exclusion *data* (`_get_own/parent_attribute_exclusions`) and
    # only characterize the traversal/pruning — exclusion extraction is covered
    # elsewhere (see test_complete_inverse_exclusions_symmetry).

    def _oracle(self, per_line, own_excl, parent_excluded):
        """Reference implementation of the engine's observable contract.

        - an empty input *list* yields nothing;
        - a non-empty list whose entries are all empty recordsets yields the
          single empty combination;
        - otherwise every one-value-per-line tuple that trips no own- or
          parent-exclusion is a valid combination.

        Exclusions are applied symmetrically (``a`` excludes ``b`` forbids the
        pair regardless of direction), matching the engine's two-way check.
        Returns a set of frozensets of ptav ids.
        """
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
        """Create a template with 2-4 no_variant attributes of 1-3 values each."""
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
        """Randomized: engine output == brute-force product+filter, over varied
        line counts/sizes, one-directional exclusions, partial and empty lines,
        and parent exclusions. Deterministic (fixed seeds) for reproducibility.
        """
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

            # Random one-directional exclusions between values of *different* lines.
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

            # Perturb the input: sometimes drop a value (partial) or empty a line.
            per_line = list(line_ptavs)
            if rng.random() < 0.3:
                idx = rng.randrange(len(per_line))
                if len(per_line[idx]) > 1:
                    per_line[idx] = per_line[idx][1:]
            if rng.random() < 0.2:
                per_line[rng.randrange(len(per_line))] = PTAV

            # Sometimes add a parent combination that excludes some of our values.
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
        """Contract: an empty input list is an empty generator (not one empty combo)."""
        self.assertEqual(
            list(
                self.child._cartesian_product(
                    [], self.env["product.template.attribute.value"]
                )
            ),
            [],
        )

    def test_cartesian_product_all_empty_lines_yields_empty_combination(self):
        """Contract: a non-empty list of empty recordsets yields exactly one empty combo."""
        PTAV = self.env["product.template.attribute.value"]
        combos = list(self.child._cartesian_product([PTAV, PTAV], PTAV))
        self.assertEqual(combos, [PTAV])

    def test_cartesian_product_fully_excluded_line_yields_nothing(self):
        """Contract: if every value of a line is parent-excluded, nothing is yielded."""
        self._add_parent_exclusion(self.child_s + self.child_m + self.child_l)
        per_line = [
            self.child.valid_product_template_attribute_line_ids.product_template_value_ids
        ]
        self.assertEqual(
            list(self.child._cartesian_product(per_line, self.sofa_red)), []
        )

    def test_document_count_counts_active_variant_documents(self):
        """D4: document count reflects the template + its active variants' documents."""
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
