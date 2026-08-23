"""Regression suite for the base_import audit.

Each test asserts the behaviour the module should have, and was written to
FAIL against the tree before the corresponding fix — 11 of 17 did. They are
kept so the fixes cannot silently regress, and so each claim stays falsifiable
rather than becoming folklore.

Claim IDs match the audit report (C*/A*/P*/D*).
"""

import base64
import contextlib
import io
import time
import unittest
import zipfile
from pathlib import Path

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, can_import


class ImportAuditChallenge(TransactionCase):
    def _imp(self, data=b"", name="t.csv", ftype="text/csv", model="res.partner"):
        return self.env["base_import.import"].create(
            {
                "res_model": model,
                "file": data,
                "file_name": name,
                "file_type": ftype,
            }
        )

    _OPTS = {"has_headers": True, "quoting": '"', "separator": ","}

    # ------------------------------------------------------------------ C3
    def test_c3_short_row_reports_import_error_not_indexerror(self):
        """A row narrower than the header must produce an import message, not
        an IndexError escaping execute_import as an HTTP 500. The precise
        message already exists for the *wider* case."""
        imp = self._imp(b"name,function\nBob,CEO\nAlice\n")
        try:
            result = imp.execute_import(
                ["name", "function"],
                ["name", "function"],
                dict(self._OPTS),
                dryrun=True,
            )
        except IndexError:
            self.fail("C3 CONFIRMED: short row raised IndexError out of execute_import")
        self.assertTrue(result.get("messages"), "expected a clean import message")

    # ------------------------------------------------------------------ C4
    def test_c4_relational_path_on_scalar_field_is_rejected_cleanly(self):
        """`name/foo` names a subfield of a Char. That is a client error and
        must surface as an import message, not KeyError('relation')."""
        imp = self._imp(b"a\nx\n")
        try:
            result = imp.execute_import(
                ["name/foo"], ["a"], dict(self._OPTS), dryrun=True
            )
        except KeyError as e:
            self.fail(f"C4 CONFIRMED: KeyError({e}) escaped execute_import")
        self.assertTrue(result.get("messages"), "the bad mapping must be reported")
        self.assertIn("not a relation", result["messages"][0]["message"])
        # Removing the crash was not enough on its own: `load` used to accept
        # `name/foo` and silently import the value into `name`, so a mapping
        # the user cannot have meant produced a record anyway. Both layers
        # refuse it now -- see `test_load_rejects_subpath_on_scalar_field`.
        self.assertFalse(
            result.get("ids"), "nothing may be created from an unusable mapping"
        )

    def test_c4_unknown_leaf_is_still_left_to_load(self):
        """The validation added for C4 must not pre-empt `load`, which
        reports unknown field names precisely."""
        imp = self._imp(b"a\nx\n")
        result = imp.execute_import(["nope"], ["a"], dict(self._OPTS), dryrun=True)
        self.assertIn("does not exist", result["messages"][0]["message"])

    # ------------------------------------------------------------------ C5
    def test_c5_header_only_file_still_suggests_mappings(self):
        """A file with headers but no data rows must still fuzzy-match its
        columns. Nothing is known about the columns, so every field is a
        candidate -- the `['all']` sentinel the type filter already handles."""
        types = self.env["base_import.import"]._extract_header_types([], {})
        self.assertEqual(
            types, ["all"], "C5 CONFIRMED: empty preview typed as %r" % (types,)
        )

        imp = self._imp(b"Functon,Displai Name\n")
        result = imp.parse_preview({"has_headers": True})
        self.assertFalse(result.get("error"))
        self.assertTrue(
            result.get("matches"),
            "C5 CONFIRMED: header-only file produced no suggestions at all",
        )

    def test_c5_control_same_file_with_data_does_suggest(self):
        """Control for the above: one data row is enough today. If this fails,
        the C5 diagnosis (empty preview_values, not the fuzzy matcher) is wrong."""
        imp = self._imp(b"Functon,Displai Name\nCEO,Bob\n")
        result = imp.parse_preview({"has_headers": True})
        self.assertEqual(result["matches"].get(0), ["function"])

    # ------------------------------------------------------------------ C6
    def test_c6_batch_flag_matches_row_count_vs_limit(self):
        """`batch` must mean "this file needs more than one batch", i.e.
        num_rows > limit. It is computed with an islice offset that only made
        sense when _read_file returned a lazy iterator."""
        imp = self._imp(b"name\n" + b"".join(b"r%d\n" % i for i in range(30)))
        wrong = []
        for limit in (5, 10, 20, 29, 30, 31, 40, 50, 100):
            preview = imp.parse_preview({"has_headers": True, "limit": limit}, count=10)
            self.assertEqual(preview["num_rows"], 30)
            expected = limit < 30
            if preview["batch"] is not expected:
                wrong.append((limit, preview["batch"], expected))
        self.assertFalse(
            wrong, "C6 CONFIRMED, wrong for (limit, got, expected): %r" % (wrong,)
        )

    # ------------------------------------------------------------------ C7
    def test_c7_saved_mapping_matches_padded_header(self):
        """The client saves `name.trim().toLowerCase()`; the server looks up
        `header.lower()`. A padded header must still hit its saved mapping."""
        self.env["base_import.mapping"].search(
            [("res_model", "=", "res.partner")]
        ).unlink()
        self.env["base_import.mapping"].create(
            {"res_model": "res.partner", "column_name": "kunde nr", "field_name": "ref"}
        )
        imp = self._imp(b'" Kunde Nr ",name\nA,Bob\n')
        result = imp.parse_preview({"has_headers": True})
        self.assertEqual(
            result["matches"].get(0),
            ["ref"],
            "C7 CONFIRMED: padded header missed its saved mapping",
        )

    def test_c7_control_unpadded_header_matches(self):
        """Control: without padding the round trip works, so the defect is the
        missing strip and not the mapping lookup as a whole."""
        self.env["base_import.mapping"].search(
            [("res_model", "=", "res.partner")]
        ).unlink()
        self.env["base_import.mapping"].create(
            {"res_model": "res.partner", "column_name": "kunde nr", "field_name": "ref"}
        )
        imp = self._imp(b"Kunde Nr,name\nA,Bob\n")
        self.assertEqual(
            imp.parse_preview({"has_headers": True})["matches"].get(0), ["ref"]
        )

    # ------------------------------------------------------------------ C8
    def test_c8_savepoint_is_released_when_conversion_crashes(self):
        """execute_import opens a savepoint and only closes it on the success
        path. A crash in _convert_import_data must not leave the cursor inside
        an unreleased savepoint."""
        imp = self._imp(b"name,function\nBob,CEO\nAlice\n")
        depth_before = self.env.cr._savepoint_depth
        with contextlib.suppress(Exception):
            imp.execute_import(
                ["name", "function"],
                ["name", "function"],
                dict(self._OPTS),
                dryrun=True,
            )
        self.assertEqual(
            self.env.cr._savepoint_depth,
            depth_before,
            "C8 CONFIRMED: savepoint depth %d -> %d, never released after the crash"
            % (depth_before, self.env.cr._savepoint_depth),
        )

    # ------------------------------------------------------------------ D2
    def test_d2_unique_constraint_exists_so_dedup_loop_is_dead(self):
        """_save_column_mappings carries a comment asserting there is no unique
        constraint on (res_model, column_name), and a `seen` loop justified by
        it. Assert the constraint really is applied -- if so the loop is dead."""
        self.env.cr.execute("""
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'base_import_mapping'::regclass
               AND contype = 'u'
               AND pg_get_constraintdef(oid) ILIKE '%%res_model, column_name%%'
        """)
        self.assertTrue(
            self.env.cr.fetchone(),
            "D2 WITHDRAWN: no unique constraint, the dedup loop is live",
        )

    # ------------------------------------------------------------------ D3
    def test_d3_type_filter_keeps_relations_and_drops_mismatched_scalars(self):
        """Pins the contract the docstring now states, after the audit found
        doc and behaviour disagreeing. Relational fields survive any
        header_types (an integer column can be a many2one by database id);
        scalar fields survive only their own type. Asserting this stops the
        next reader "fixing" the elif and silently changing every suggestion
        the module makes."""
        Imp = self.env["base_import.import"]
        tree = Imp.get_fields_tree("res.partner")
        kept = Imp._filter_fields_by_types(tree, ["integer"])

        relational = {"many2one", "one2many", "many2many"}
        scalars = [f for f in kept if f["type"] not in relational]
        self.assertTrue(
            all(f["type"] in ("integer", "id") for f in scalars),
            "mismatched scalar kept: %r" % ([f["name"] for f in scalars],),
        )
        # and the relations really are all still there
        self.assertEqual(
            len([f for f in kept if f["type"] in relational]),
            len([f for f in tree if f["type"] in relational]),
        )

    def test_d3_all_sentinel_keeps_everything(self):
        """The `['all']` sentinel C5 restored must survive the filter."""
        Imp = self.env["base_import.import"]
        tree = Imp.get_fields_tree("res.partner")
        self.assertEqual(len(Imp._filter_fields_by_types(tree, ["all"])), len(tree))

    # ------------------------------------------------------------------ A1
    def test_a1_get_fields_tree_checks_access_on_the_entry_model(self):
        """The audit first filed this as disclosure and then downgraded it:
        the tree is *narrower* than the `fields_get` it wraps (14 fields vs 21
        on ir.mail_server), so it discloses nothing that model's own
        `fields_get` does not already hand out. The check added is defence in
        depth against the reach one call gives -- ~49 comodels, three levels
        deep -- not a closed hole."""
        user = self.env["res.users"].create(
            {
                "name": "audit probe",
                "login": "audit_probe_user",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        model = "ir.mail_server"
        self.assertFalse(self.env[model].with_user(user).has_access("read"))
        with self.assertRaises(AccessError):
            self.env["base_import.import"].with_user(user).get_fields_tree(model)

    def test_a1_readable_model_still_works_and_recursion_is_not_checked(self):
        """The check is on the entry model only. A user who can read
        res.partner must still get the whole tree, including comodels they
        cannot read directly but must be able to map onto."""
        user = self.env["res.users"].create(
            {
                "name": "audit probe 2",
                "login": "audit_probe_user_2",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        Imp = self.env["base_import.import"].with_user(user)
        tree = Imp.get_fields_tree("res.partner")
        self.assertTrue(tree)
        reached = set()

        def walk(nodes):
            for node in nodes:
                if node.get("comodel_name"):
                    reached.add(node["comodel_name"])
                walk(node.get("fields") or [])

        walk(tree)
        unreadable = [
            m
            for m in reached
            if m in self.env and not self.env[m].with_user(user).has_access("read")
        ]
        self.assertTrue(
            unreadable,
            "expected the tree to still descend into models the user cannot read",
        )


class ImportAuditChallengePerf(TransactionCase):
    """Performance claims. Asserted as loose bounds so they fail only on the
    order of magnitude the audit actually claimed, not on machine noise."""

    def test_p1_encoding_detection_is_not_linear_in_file_size(self):
        """Detection used to hand the whole buffer to `chardet.detect`, which
        runs its full prober suite over every byte once the file contains a
        single non-ASCII character: 12-17s on a few MiB, i.e. every file in a
        non-English deployment."""
        import chardet

        from odoo.addons.base_import.models.base_import import _detect_encoding

        data = (
            b"name,ref\n"
            + b"".join(b"Row %d,R%d\n" % (i, i) for i in range(150000))
            + "café déjà,R\n".encode()
        )

        start = time.perf_counter()
        detected = _detect_encoding(data)
        elapsed = time.perf_counter() - start

        # Same answer as the one-shot call -- the speed is worth nothing if the
        # encoding changes, and a head-sample version (the obvious fix, which
        # the audit tried first) reports `ascii` here and then fails to decode.
        self.assertEqual(detected.lower(), chardet.detect(data)["encoding"].lower())
        self.assertTrue(data.decode(detected).endswith("café déjà,R\n"))
        self.assertLess(
            elapsed,
            1.0,
            "P1 REGRESSED: detection took %.1fs on %.1f MiB"
            % (elapsed, len(data) / 2**20),
        )

    def test_p2_multi_mapping_does_not_resolve_types_per_row(self):
        """_handle_multi_mapping walks the field path through the registry
        inside the row loop. Nothing in that walk depends on the row."""
        imp = self.env["base_import.import"].create({"res_model": "res.partner"})
        rows = [["a%d" % i, "b%d" % i, "c%d" % i] for i in range(20000)]
        start = time.perf_counter()
        imp.with_context(import_options={})._handle_multi_mapping(
            ["name", "comment", "ref"], rows
        )
        elapsed = time.perf_counter() - start
        self.assertLess(
            elapsed,
            0.08,
            "P2 CONFIRMED: %.3fs for 20k rows x 3 fields; hoisting the type "
            "resolution out of the loop measures ~7x faster" % elapsed,
        )


@unittest.skipUnless(can_import("odf"), "odfpy not installed")
class ODSReaderChallenge(TransactionCase):
    """C1/C2. Both files are built by rewriting content.xml of a real
    LibreOffice-produced spreadsheet, so they are spec-legal ODF rather than
    synthetic odfpy documents.
    """

    _CSV = b"name,note,qty\nAlice,plain text,1\nBob,dup row,2\nCarol,cafe deja,3\n"

    def _ods(self, transform=None):
        """Build a minimal but spec-shaped ODS, optionally rewriting its XML."""
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import Table, TableCell, TableRow
        from odf.text import P

        doc = OpenDocumentSpreadsheet()
        table = Table(name="Sheet1")
        for line in self._CSV.decode().strip().split("\n"):
            row = TableRow()
            for cell_text in line.split(","):
                cell = TableCell()
                cell.addElement(P(text=cell_text))
                row.addElement(cell)
            row.addElement(TableCell())
            table.addElement(row)
        doc.spreadsheet.addElement(table)

        buf = io.BytesIO()
        doc.write(buf)
        raw = buf.getvalue()
        if transform is None:
            return raw

        zin = zipfile.ZipFile(io.BytesIO(raw))
        content = transform(zin.read("content.xml").decode("utf-8"))
        out = io.BytesIO()
        zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
        for item in zin.infolist():
            payload = zin.read(item.filename)
            if item.filename == "content.xml":
                payload = content.encode("utf-8")
            zout.writestr(item, payload)
        zout.close()
        return out.getvalue()

    def _read(self, raw):
        from odoo.addons.base_import.models import odf_ods_reader

        reader = odf_ods_reader.ODSReader(file=io.BytesIO(raw))
        return reader.get_sheet(next(iter(reader.sheets)))

    def test_c1_cell_with_styled_span_is_readable(self):
        """A cell whose text is partially styled carries a <text:span>. The
        extraction loop reads `n.data` -- the span element -- instead of
        `c.data`, the text node it just tested."""
        raw = self._ods(
            lambda c: c.replace(
                "<text:p>plain text</text:p>",
                '<text:p>plain <text:span text:style-name="T1">bold</text:span> tail</text:p>',
                1,
            )
        )
        try:
            rows = self._read(raw)
        except AttributeError as e:
            self.fail("C1 CONFIRMED: styled span raises AttributeError(%s)" % e)
        flat = [cell for row in rows for cell in row]
        self.assertIn(
            "plain bold tail",
            flat,
            "C1 PARTIAL: no crash, but the span text was lost: %r" % (rows,),
        )

    def test_c1_end_to_end_user_sees_unreadable_file(self):
        """The same file through the real entry point."""
        raw = self._ods(
            lambda c: c.replace(
                "<text:p>plain text</text:p>",
                '<text:p>plain <text:span text:style-name="T1">bold</text:span> tail</text:p>',
                1,
            )
        )
        imp = self.env["base_import.import"].create(
            {
                "res_model": "res.partner",
                "file": raw,
                "file_name": "span.ods",
                "file_type": "application/vnd.oasis.opendocument.spreadsheet",
            }
        )
        result = imp.parse_preview({"has_headers": True})
        self.assertFalse(
            result.get("error"),
            "C1 CONFIRMED end to end, user sees: %s" % result.get("error"),
        )

    def test_c2_repeated_content_rows_are_expanded(self):
        """number-rows-repeated on a row carrying content must yield that many
        rows. readSheet honours the columns attribute and ignores the rows one,
        so the extra rows vanish with no error.

        Note: LibreOffice does NOT emit this for identical consecutive rows
        (verified), so this is a spec-conformance gap affecting other
        producers, not a defect every ODS upload hits.
        """
        raw = self._ods(
            lambda c: c.replace(
                "<table:table-row>",
                '<table:table-row table:number-rows-repeated="4">',
                1,
            )
        )
        rows = self._read(raw)
        self.assertEqual(
            len(rows),
            len(self._CSV.decode().strip().split("\n")) + 3,
            "C2 CONFIRMED: repeated row collapsed, got %d rows" % len(rows),
        )

    def test_c2_control_libreoffice_does_not_collapse_identical_rows(self):
        """Control for the claim withdrawn above: a real LibreOffice CSV->ODS
        conversion writes identical consecutive rows out in full."""
        path = Path("/home/marin/bimp_lo/src.ods")
        if not path.exists():
            self.skipTest("reference LibreOffice file not present")
        raw = path.read_bytes()
        content = zipfile.ZipFile(io.BytesIO(raw)).read("content.xml").decode()
        self.assertNotIn("number-rows-repeated", content)


class BinaryFilenameAlignment(TransactionCase):
    """B1. `execute_import` reports local-file cells back to the client, which
    pairs them with the ids `load` returned by index. That pairing only holds
    if both lists count the same things -- and one counted rows while the other
    counted records.
    """

    _OPTS = {"has_headers": True, "quoting": '"', "separator": ","}

    def _imp(self, data):
        return self.env["base_import.import"].create(
            {
                "res_model": "res.partner",
                "file": data,
                "file_name": "t.csv",
                "file_type": "text/csv",
            }
        )

    def test_b1_filenames_are_per_record_not_per_row(self):
        """A one2many continuation row belongs to the record above it, so it
        must not consume an entry. It used to: the second record was handed the
        continuation row's image and the third row's image was never uploaded.
        """
        imp = self._imp(
            b"name,child_ids/name,image_1920\n"
            b"Parent,Kid1,parent.png\n"
            b",Kid2,continuation.png\n"
            b"Other,Kid3,other.png\n"
        )
        result = imp.execute_import(
            ["name", "child_ids/name", "image_1920"],
            ["name", "child_ids/name", "image_1920"],
            dict(self._OPTS),
            dryrun=True,
        )

        ids = result.get("ids") or []
        filenames = (result.get("binary_filenames") or {}).get("image_1920") or []
        self.assertEqual(len(ids), 2, "3 rows, 2 records")
        self.assertEqual(
            filenames,
            ["parent.png", "other.png"],
            "each record must get its own file, not the next row's",
        )
        self.assertEqual(len(filenames), len(ids))

    def test_b1_names_are_per_record_too(self):
        """`name` is zipped against `ids` by the same client code."""
        imp = self._imp(b"name,child_ids/name\nParent,Kid1\n,Kid2\nOther,Kid3\n")
        result = imp.execute_import(
            ["name", "child_ids/name"],
            ["name", "child_ids/name"],
            dict(self._OPTS),
            dryrun=True,
        )
        self.assertEqual(result["name"], ["Parent", "Other"])
        self.assertEqual(len(result["name"]), len(result["ids"]))

    def test_b1_plain_file_still_aligns(self):
        """Control: with no one2many column, rows and records coincide and
        nothing about the ordinary case changes."""
        imp = self._imp(b"name,image_1920\nA,a.png\nB,b.png\nC,c.png\n")
        result = imp.execute_import(
            ["name", "image_1920"],
            ["name", "image_1920"],
            dict(self._OPTS),
            dryrun=True,
        )
        self.assertEqual(
            result["binary_filenames"]["image_1920"], ["a.png", "b.png", "c.png"]
        )
        self.assertEqual(len(result["ids"]), 3)

    def test_b1_continuation_file_fills_an_empty_parent(self):
        """A file named on a continuation row still belongs to the record that
        row feeds, so it is used when that record named none of its own."""
        imp = self._imp(
            b"name,child_ids/name,image_1920\nParent,Kid1,\n,Kid2,late.png\n"
        )
        result = imp.execute_import(
            ["name", "child_ids/name", "image_1920"],
            ["name", "child_ids/name", "image_1920"],
            dict(self._OPTS),
            dryrun=True,
        )
        self.assertEqual(result["binary_filenames"]["image_1920"], ["late.png"])

    def test_b2_load_accepts_null_and_empty_in_a_binary_column(self):
        """BinaryFileManager builds each row as `Array(n)` and fills only the
        columns that record has a file for, so the rest serialise as `null`.

        That reads like a latent bug and is not one — pinned here so nobody
        "fixes" it. The audit briefly believed it was, on the strength of a
        probe that used an invalid PNG: the rejection came from the image
        bytes, not the placeholder. With a real image both `None` and `""` are
        accepted for the untouched column.
        """
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (4, 4), (255, 0, 0)).save(buffer, "PNG")
        image = base64.b64encode(buffer.getvalue()).decode()

        for placeholder in (None, ""):
            partner = self.env["res.partner"].create({"name": "binary holes"})
            result = (
                self.env["res.partner"]
                .with_context(import_file=True)
                .load(
                    [".id", "image_1920", "image_128"],
                    [[str(partner.id), image, placeholder]],
                )
            )
            self.assertTrue(
                result["ids"],
                "placeholder %r rejected: %r" % (placeholder, result["messages"]),
            )
            self.assertFalse(result["messages"])


class LoadFieldPathValidation(TransactionCase):
    """`load` validated field paths asymmetrically: a bad subpath under a
    relation was refused, while one under a scalar was silently truncated to
    its first segment and imported there."""

    def test_load_rejects_subpath_on_scalar_field(self):
        """`name/foo` used to create a partner named after the value, because
        `_extract_records` keys records on `fnames[0]` and drops the rest. The
        user asked for something that cannot exist; producing a record anyway
        is the one outcome that hides the mistake."""
        for path in ("name/foo", "name/id", "name/foo/bar"):
            result = (
                self.env["res.partner"]
                .with_context(import_file=True)
                .load([path], [["Zeta"]])
            )
            self.assertFalse(result["ids"], "%s silently imported" % path)
            self.assertIn("is not a relation", result["messages"][0]["message"])
            self.assertEqual(result["messages"][0]["field_path"], path.split("/"))

    def test_load_still_accepts_real_relational_paths(self):
        """Control: the check must not touch paths that do address something."""
        country = self.env["res.country"].search([("code", "=", "BE")], limit=1)
        result = (
            self.env["res.partner"]
            .with_context(import_file=True)
            .load(["name", "country_id/id"], [["Rel path", "base.be"]])
        )
        self.assertTrue(result["ids"], result["messages"])
        self.assertEqual(
            self.env["res.partner"].browse(result["ids"]).country_id, country
        )

    def test_load_leaves_unknown_leaf_names_to_the_converter(self):
        """An unknown field is reported per row by the converter, with the
        model name. Pre-empting it here would only produce a worse message."""
        result = (
            self.env["res.partner"]
            .with_context(import_file=True)
            .load(["nope"], [["x"]])
        )
        self.assertIn("does not exist", result["messages"][0]["message"])


class SelectionLabelLanguage(TransactionCase):
    """Importing a selection column must accept the label in the source
    language as well as the user's, because exported files routinely carry
    English labels while the session is in another language."""

    def test_source_labels_are_indexed_alongside_translated_ones(self):
        """`_get_selection_and_labels` asked for the source labels with
        `lang=None`. That is not "no translation": `_()` resolves its language
        by walking the stack for a frame whose `self.env.lang` is truthy, so a
        `None` lang is a frame to skip and the walk found the caller's French.
        Only the French labels were indexed, and a file written with the
        English ones failed with "Value 'Wheee' not found in selection field".
        """
        from odoo.tools.translate import code_translations

        self.env["res.lang"]._activate_lang("fr_FR")
        code_translations.python_translations[("test_import_export", "fr_FR")] = {
            "Corge": "toto",
            "Grault": "titi",
            "Wheee": "tete",
            "Moog": "tutu",
        }
        self.addCleanup(
            code_translations.python_translations.pop, ("test_import_export", "fr_FR")
        )

        converter = self.env["ir.fields.converter"].with_context(lang="fr_FR")
        field = self.env["export.selection.function"]._fields["value"]
        index = converter._get_selection_index(field)

        for label in ("wheee", "corge", "grault", "moog"):
            self.assertIn(label, index, "source label %r not importable" % label)
        for label in ("tete", "toto", "titi", "tutu"):
            self.assertIn(label, index, "translated label %r not importable" % label)
