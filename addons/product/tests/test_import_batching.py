import csv
import io

from odoo.tests import TransactionCase, tagged

from odoo.addons.product.tests.common import ProductCommon

FIELDS = ["name", "import_attribute_values"]
IMPORT_OPTIONS = {
    "has_headers": True,
    "quoting": '"',
    "separator": ",",
    "encoding": "utf-8",
    "date_format": "",
    "datetime_format": "",
    "float_thousand_separator": ",",
    "float_decimal_separator": ".",
    "advanced": True,
    "keep_matches": False,
    "name_create_enabled_fields": {},
    "import_skip_records": [],
    "import_set_empty_fields": [],
    "fallback_values": {},
    "tracking_disable": True,
}


class ImportCase(TransactionCase):

    def setUp(self):
        super().setUp()
        if "base_import.import" not in self.env:
            self.skipTest("base_import is not installed")

    def _run_import(self, rows, limit):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerows([FIELDS, *rows])
        wizard = self.env["base_import.import"].create(
            {
                "res_model": "product.template",
                "file": buffer.getvalue().encode(),
                "file_type": "text/csv",
                "file_name": "batch.csv",
            }
        )
        wizard.parse_preview({**IMPORT_OPTIONS})

        next_rows, errors, skip = [], [], 0
        for _round in range(len(rows) + 2):
            result = wizard.execute_import(
                FIELDS, FIELDS, {**IMPORT_OPTIONS, "limit": limit, "skip": skip}
            )
            errors += [
                message
                for message in result["messages"]
                if message.get("type") == "error"
            ]
            next_rows.append(result["nextrow"])
            if errors or not result["nextrow"]:
                return next_rows, errors
            skip = result["nextrow"]
        return self.fail(f"the import never terminated: nextrow was {next_rows}")

    def _imported(self, prefix):
        return self.env["product.template"].search([("name", "=like", f"{prefix}%")])


@tagged("post_install", "-at_install")
class TestImportBatching(ImportCase, ProductCommon):

    def test_interleaved_file_imports_completely(self):
        rows = [
            ["Mix T1", ""],
            ["Mix V1", "MixColor:Red"],
            ["Mix T2", ""],
            ["Mix V2", "MixColor:Blue"],
            ["Mix T3", ""],
            ["Mix V3", "MixColor:Green"],
        ]
        next_rows, errors = self._run_import(rows, limit=2)

        self.assertFalse(errors, errors)
        self.assertEqual(
            sorted(self._imported("Mix ").mapped("name")),
            sorted(row[0] for row in rows),
            f"every batch is one template row and one variant row; nextrow"
            f" went {next_rows}",
        )

    def test_grouped_file_still_imports_completely(self):
        rows = [
            ["Grp T1", ""],
            ["Grp T2", ""],
            ["Grp T3", ""],
            ["Grp T4", ""],
            ["Grp V1", "GrpColor:Red"],
            ["Grp V2", "GrpColor:Blue"],
        ]
        next_rows, errors = self._run_import(rows, limit=2)

        self.assertFalse(errors, errors)
        self.assertEqual(next_rows, [2, 4, 6, 0])
        self.assertEqual(
            sorted(self._imported("Grp ").mapped("name")),
            sorted(row[0] for row in rows),
        )

    def test_a_file_shorter_than_the_batch_ends_at_once(self):
        rows = [["Short T1", ""], ["Short V1", "ShortColor:Red"]]
        next_rows, errors = self._run_import(rows, limit=1000)

        self.assertFalse(errors, errors)
        self.assertEqual(next_rows, [0], "a batch that is not full is the last one")
        self.assertEqual(len(self._imported("Short ")), 2)

    def test_every_row_is_imported_exactly_once(self):
        rows = [
            [
                f"Once {'V' if index % 3 else 'T'}{index}",
                "OnceColor:Red" if index % 3 else "",
            ]
            for index in range(9)
        ]
        _next_rows, errors = self._run_import(rows, limit=2)

        self.assertFalse(errors, errors)
        names = self._imported("Once ").mapped("name")
        self.assertEqual(len(names), len(set(names)), "a row was imported twice")
        self.assertEqual(sorted(names), sorted(row[0] for row in rows))


@tagged("post_install", "-at_install")
class TestImportMessageRows(ImportCase, ProductCommon):

    def test_error_row_is_reported_against_the_imported_batch(self):
        rows = [
            ["Row T1", ""],
            ["Row T2", ""],
            ["Row T3", ""],
            ["Row V1", "RowColor:Red,RowColor:Blue"],
        ]
        _next_rows, errors = self._run_import(rows, limit=1000)

        self.assertTrue(errors, "the malformed row must be reported")
        self.assertEqual(
            {message.get("record") for message in errors},
            {3},
            "the row reported is the fourth of the batch, not the first of the"
            " variant partition",
        )


@tagged("post_install", "-at_install")
class TestImportRowIsolation(ProductCommon):

    def test_rows_are_not_rewritten_in_place(self):
        rows = [
            {"name": "Iso Widget", "import_attribute_values": "IsoColor:Red"},
            {"name": "Iso Widget", "import_attribute_values": "IsoColor:Blue"},
        ]
        original = [dict(row) for row in rows]
        self.env["product.product"].with_context(
            import_file=True,
            create_product_product=False,
        )._load_records_create(rows)
        self.assertEqual(rows, original)

    def test_an_empty_cell_does_not_reset_a_shared_template_field(self):
        self.env["product.template"].with_context(import_file=True).load(
            ["name", "import_attribute_values", "list_price"],
            [
                ["Shared Shirt", "SharedColor:Red", "10"],
                ["Shared Shirt", "SharedColor:Blue", ""],
            ],
        )
        template = self.env["product.template"].search([("name", "=", "Shared Shirt")])
        self.assertEqual(len(template), 1)
        self.assertEqual(len(template.product_variant_ids), 2)
        self.assertEqual(template.list_price, 10.0)

    def test_a_same_named_template_is_left_alone(self):
        bystander, target = self.env["product.template"].create(
            [
                {"name": "Twin Product", "default_code": "TWIN-A"},
                {"name": "Twin Product", "default_code": "TWIN-B"},
            ]
        )
        bystander_variant = bystander.product_variant_ids
        self.assertTrue(bystander_variant)

        result = (
            self.env["product.template"]
            .with_context(import_file=True)
            .load(
                ["name", "import_attribute_values"],
                [["Twin Product", "TwinColor:Red"]],
            )
        )
        self.assertFalse(
            [m for m in result["messages"] if m["type"] == "error"], result["messages"]
        )
        self.assertTrue(
            bystander_variant.exists(),
            "the same-named product the import did not target kept its variant",
        )
        self.assertTrue(bystander.product_variant_ids)
        imported = (
            (bystander | target)
            .with_context(active_test=False)
            .product_variant_ids.product_template_attribute_value_ids
        )
        self.assertEqual(imported.mapped("name"), ["Red"])

    def test_a_variant_only_column_does_not_abort_the_import(self):
        for column in ("additional_product_tag_ids", "image_variant_1920"):
            with self.subTest(column=column):
                result = (
                    self.env["product.template"]
                    .with_context(import_file=True)
                    .load(
                        ["name", "import_attribute_values", column],
                        [[f"Col {column}", "ColColor:Red", ""]],
                    )
                )
                self.assertFalse(
                    [m for m in result["messages"] if m["type"] == "error"],
                    result["messages"],
                )
                self.assertTrue(result["ids"])

    def test_a_failing_row_does_not_invent_errors_for_the_others(self):
        rows = [
            ["Phantom A", "PhantomColor:Red", "10"],
            ["Phantom B", "PhantomColor:Blue", "-5"],
            ["Phantom C", "PhantomColor:Green", "7"],
        ]
        result = (
            self.env["product.template"]
            .with_context(import_file=True)
            .load(["name", "import_attribute_values", "standard_price"], rows)
        )
        messages = [
            message["message"]
            for message in result["messages"]
            if message["type"] == "error"
        ]
        self.assertTrue(messages, "the negative cost must be reported")
        self.assertTrue(
            all("cost of a product" in message for message in messages),
            f"every error must name the real cause, got {messages}",
        )

    def test_import_onto_a_template_whose_variants_are_all_archived(self):
        template = self.env["product.template"].create(
            {"name": "Archived Widget", "default_code": "ARCH-1"}
        )
        template.product_variant_ids.write({"active": False})
        self.assertTrue(template.active)
        self.assertFalse(template.product_variant_ids)

        result = (
            self.env["product.template"]
            .with_context(import_file=True)
            .load(
                ["name", "import_attribute_values", "default_code", "description_sale"],
                [["Archived Widget", "ArchColor:Red", "", ""]],
            )
        )
        self.assertFalse(
            [m for m in result["messages"] if m["type"] == "error"],
            result["messages"],
        )
        self.assertEqual(
            template.with_context(active_test=False).product_variant_ids.mapped(
                "product_template_attribute_value_ids.name"
            ),
            ["Red"],
        )
