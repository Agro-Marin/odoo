"""`odoo._monkeypatches`: applied, idempotent, and order-independent.

Moved from `odoo/addons/base/tests/test_monkeypatches.py`. It subclassed the framework test
case but touched no database and no registry, so it only ran behind a
`createdb` plus a full `base` install. It does need a real `import odoo.*`,
which is why it is here rather than in a Tier-1 suite.
"""

import ast as ast_module
import copy
import importlib
import io
import pathlib
import pkgutil
import sys
import unittest

import odoo._monkeypatches as monkeypatches
from odoo.tools import mute_logger


def _patch_submodules():
    return [
        module.name
        for module in pkgutil.iter_modules(monkeypatches.__path__)
        if not module.name.startswith("_")
    ]


class TestMonkeypatchContract(unittest.TestCase):
    def test_submodules_discovered(self):
        self.assertTrue(
            _patch_submodules(), "no monkeypatch submodules were discovered"
        )

    def test_every_patch_exposes_callable_patch_module(self):
        for name in _patch_submodules():
            with self.subTest(patch=name):
                module = importlib.import_module(f"odoo._monkeypatches.{name}")
                self.assertTrue(
                    callable(getattr(module, "patch_module", None)),
                    f"odoo._monkeypatches.{name} must define a callable "
                    f"patch_module() (see odoo/_monkeypatches/README.md)",
                )

    def test_every_patch_imports_the_module_it_is_named_for(self):
        """The file name is the wiring, so it has to name a module we touch.

        `patch_init()` derives the hook set from file names and nothing else
        declares what a file patches, so a file named for an unrelated module
        still runs -- hooked on *that* module's import -- and the README index
        inherits the lie. `site.py` was that file: it patched `odoo`,
        `encodings.aliases`, `codecs` and `babel.core`, and nothing named
        `site`. An import of the target counts wherever it appears, including
        inside `patch_module()` (`num2words.py` imports lazily on purpose).
        """
        for name in _patch_submodules():
            with self.subTest(patch=name):
                source = pathlib.Path(
                    monkeypatches.__path__[0], f"{name}.py"
                ).read_text(encoding="utf-8")
                roots = set()
                for node in ast_module.walk(ast_module.parse(source)):
                    if isinstance(node, ast_module.Import):
                        roots.update(a.name.partition(".")[0] for a in node.names)
                    elif isinstance(node, ast_module.ImportFrom) and node.module:
                        roots.add(node.module.partition(".")[0])
                self.assertIn(
                    name,
                    roots,
                    f"odoo._monkeypatches.{name} imports {sorted(roots)} and never "
                    f"{name!r}, the module its name promises the hook it patches",
                )


class TestPatchesSurviveEitherImportOrder(unittest.TestCase):
    def test_importing_every_submodule_leaves_every_patch_applied(self):
        """Importing a patch submodule must apply its patch, not disable it.

        A patch submodule imports its target at module level, so importing the
        submodule first re-enters `patch_module()` while the submodule is still
        initializing.  That call used to return silently and the patch was
        dropped for the life of the process -- unlogged, and absent from the
        applied set, so nothing downstream could tell.

        This very walk is what triggered it: it disabled 9 of 14 patches, `csv`
        among them, which is why `test_translate_csv_dialect_is_registered`
        below is the second half of this regression.
        """
        for name in _patch_submodules():
            importlib.import_module(f"odoo._monkeypatches.{name}")

        self.assertEqual(
            monkeypatches.HOOK_IMPORT.hooks - monkeypatches.applied(),
            set(),
            "hooked patches left unapplied after their submodules were imported",
        )

    def test_patching_is_idempotent(self):
        applied = set(monkeypatches.applied())
        self.assertTrue(applied, "nothing has been patched; test is vacuous")
        for name in applied:
            monkeypatches.patch_module(name)
        self.assertEqual(applied, set(monkeypatches.applied()))

    def test_applied_is_a_subset_of_the_hooks(self):
        self.assertLessEqual(monkeypatches.applied(), monkeypatches.HOOK_IMPORT.hooks)


class TestLoaderCapabilitiesSurvivePatching(unittest.TestCase):
    def _hooked_and_wrapped(self):
        from odoo._monkeypatches import _PatchingLoader

        return [
            name
            for name in monkeypatches.HOOK_IMPORT.hooks
            if isinstance(
                getattr(sys.modules.get(name), "__loader__", None), _PatchingLoader
            )
        ]

    def test_the_wrapper_is_actually_exercised(self):
        self.assertTrue(
            self._hooked_and_wrapped(),
            "no hooked module carries a _PatchingLoader; the capability "
            "assertions below would pass trivially",
        )

    def test_wrapped_loaders_delegate_their_capabilities(self):
        for name in self._hooked_and_wrapped():
            loader = sys.modules[name].__loader__
            underlying = loader._loader
            with self.subTest(module=name):
                for capability in (
                    "get_source",
                    "get_data",
                    "get_resource_reader",
                    "is_package",
                ):
                    self.assertEqual(
                        hasattr(loader, capability),
                        hasattr(underlying, capability),
                        f"{name}: wrapper hides {capability}",
                    )


class TestCsvPatch(unittest.TestCase):
    def test_field_size_limit_admits_an_inline_image(self):
        """128KiB is the stdlib default; the reader raises rather than truncate."""
        import csv

        self.assertGreaterEqual(csv.field_size_limit(), 500 * 1024 * 1024)

    def test_the_limit_is_actually_enforced_at_that_size(self):
        import csv
        import io

        big = "x" * (200 * 1024)
        rows = list(csv.reader(io.StringIO(f'"{big}"')))
        self.assertEqual(len(rows[0][0]), len(big))


class TestAstLiteralEvalLimit(unittest.TestCase):
    def test_oversized_expression_is_refused(self):
        import ast

        with self.assertRaises(ValueError):
            ast.literal_eval("'" + "x" * 200_000 + "'")

    def test_ordinary_expression_still_evaluates(self):
        import ast

        self.assertEqual(ast.literal_eval("{'a': [1, 2]}"), {"a": [1, 2]})

    def test_an_ast_node_is_not_length_checked(self):
        import ast

        self.assertEqual(ast.literal_eval(ast.parse("[1, 2]", mode="eval")), [1, 2])

    @mute_logger("odoo._monkeypatches.ast")
    def test_the_env_var_is_resolved_once_and_validated(self):
        """Read per call it cost ~9% of literal_eval, and logged once per call.

        Muted because three of the cases below are meant to log an ERROR; an
        ERROR line in a green run trains people to skim past them.
        """
        from odoo._monkeypatches.ast import DEFAULT_BUFFER_SIZE, buffer_size_from_env

        for raw, expected in (
            (None, DEFAULT_BUFFER_SIZE),
            ("", DEFAULT_BUFFER_SIZE),
            ("nonsense", DEFAULT_BUFFER_SIZE),
            ("0", DEFAULT_BUFFER_SIZE),
            ("-5", DEFAULT_BUFFER_SIZE),
            ("4096", 4096),
        ):
            with (
                self.subTest(raw=raw),
                self.patch_env("ODOO_LIMIT_LITEVAL_BUFFER", raw),
            ):
                self.assertEqual(buffer_size_from_env(), expected)

    def patch_env(self, name, value):
        import contextlib
        import os

        @contextlib.contextmanager
        def _ctx():
            previous = os.environ.get(name)
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
            try:
                yield
            finally:
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous

        return _ctx()


class TestEmailHeaderFolding(unittest.TestCase):
    def _render(self, header, value):
        import email.policy
        from email.message import EmailMessage

        message = EmailMessage(policy=email.policy.SMTP)
        message["From"] = "sender@example.com"
        message[header] = value
        return message.as_string()

    def _continuation_lines(self, rendered):
        return [line for line in rendered.splitlines() if line.startswith((" ", "\t"))]

    def test_identification_headers_are_never_folded(self):
        """Folding is legal and reversible; this is defensive interop.

        A folded header re-parses to the same value, so nothing is *corrupted*
        -- what the patch buys is that naive consumers matching msg-ids as
        strings, and archived `original_email.eml` blobs, see one line.
        `In-Reply-To`, `References` and `Resent-Message-ID` all fold under the
        stock policy; `Message-Id` does not (stdlib gives it an unfoldable
        header class), so that member is vacuous and kept for the contract.

        `Resent-Message-ID` is here because the set used to spell it
        `resent-msg-id`, which is not a header name and so matched nothing.
        """
        references = " ".join(f"<msg-{i}.odoo@example.com>" for i in range(8))
        for header in ("Message-Id", "In-Reply-To", "References", "Resent-Message-ID"):
            with self.subTest(header=header):
                self.assertEqual(
                    self._continuation_lines(self._render(header, references)),
                    [],
                    f"{header} was folded",
                )

    def test_user_headers_fold_only_at_the_rfc_5322_limit(self):
        rendered = self._render("Subject", "x" * 400)
        self.assertEqual(self._continuation_lines(rendered), [])
        self.assertLessEqual(max(len(line) for line in rendered.splitlines()), 998)

    def test_other_headers_keep_the_stdlib_fold(self):
        rendered = self._render("X-Odoo-Trace", "y " * 200)
        self.assertTrue(self._continuation_lines(rendered))

    def test_the_policy_carries_the_stdlib_smtp_line_ending(self):
        import email.policy

        self.assertEqual(email.policy.SMTP.linesep, "\r\n")


class TestExcelSheetNames(unittest.TestCase):
    def _sanitize(self, name, taken=()):
        from odoo._monkeypatches._excel_utils import sanitize_excel_sheet_name

        return sanitize_excel_sheet_name(name, taken)

    def test_invalid_characters_are_dropped(self):
        self.assertEqual(self._sanitize("a[b]c:d*e?f/g\\h"), "abcdefgh")

    def test_edge_apostrophes_are_dropped(self):
        """xlsxwriter rejects them outright; the sanitizer used to pass them through."""
        self.assertEqual(self._sanitize("'quoted'"), "quoted")

    def test_names_are_cut_to_the_excel_limit(self):
        self.assertEqual(len(self._sanitize("n" * 60)), 31)

    def test_truncation_does_not_manufacture_a_duplicate(self):
        """Truncating is what creates the clash, so the sanitizer has to break it."""
        first = self._sanitize("Journal Items 2026 - Ledger A")
        second = self._sanitize("Journal Items 2026 - Ledger B", [first])
        self.assertNotEqual(first.lower(), second.lower())
        self.assertLessEqual(len(second), 31)

    def test_duplicate_detection_ignores_case_as_excel_does(self):
        self.assertNotEqual(self._sanitize("Sales", ["SALES"]).lower(), "sales")

    def test_the_workbook_accepts_two_long_names_that_share_a_prefix(self):
        import xlsxwriter

        workbook = xlsxwriter.Workbook(io.BytesIO(), {"in_memory": True})
        names = [
            workbook.add_worksheet(f"Journal Items 2026 - Extremely Long {suffix}").name
            for suffix in "AB"
        ]
        self.assertEqual(len(set(names)), 2, f"{names} collided after truncation")

    def test_strings_are_not_turned_into_live_formulas(self):
        import xlsxwriter

        workbook = xlsxwriter.Workbook(io.BytesIO(), {"in_memory": True})
        self.assertFalse(workbook.strings_to_formulas)


class TestMimeTypePins(unittest.TestCase):
    PINS = (
        (".woff", "font/woff"),
        (".eot", "application/vnd.ms-fontobject"),
        (".ttf", "font/ttf"),
        (".webp", "image/webp"),
        (".svg", "image/svg+xml"),
        (".js", "text/javascript"),
    )

    def test_the_six_extensions_resolve_to_the_web_types(self):
        """Vacuous on its own, and kept anyway: it states the contract.

        CPython 3.14's hardcoded table already agrees on all six, so this
        passes with `mimetypes.py` deleted. The test below is the one that
        measures the patch.
        """
        import mimetypes

        for extension, expected in self.PINS:
            with self.subTest(extension=extension):
                self.assertEqual(mimetypes.guess_type(f"f{extension}")[0], expected)

    def test_the_pins_survive_a_host_mapping_that_disagrees(self):
        """This is the patch's whole job, and the only non-vacuous form of it.

        `mimetypes.init()` rebuilds the database from `knownfiles` -- a distro
        `/etc/mime.types`, or the Windows registry -- and whatever it reads
        overrides CPython's defaults *and* silently discards every earlier
        `add_type`. Serving `.js` as `text/plain` is a broken web client, so
        the pin has to outlive the rebuild rather than race it.
        """
        import mimetypes
        import pathlib
        import tempfile

        self.addCleanup(mimetypes.init)

        hostile = pathlib.Path(tempfile.mkdtemp(), "mime.types")
        hostile.write_text(
            "text/plain\tjs\napplication/octet-stream\tsvg webp\n", encoding="utf-8"
        )
        mimetypes.init([str(hostile)])

        for extension, expected in self.PINS:
            with self.subTest(extension=extension):
                self.assertEqual(mimetypes.guess_type(f"f{extension}")[0], expected)

    def test_the_host_file_really_would_have_won(self):
        """Guards the test above: without the wrapper, `init()` wins."""
        import mimetypes
        import pathlib
        import tempfile

        self.addCleanup(mimetypes.init)

        hostile = pathlib.Path(tempfile.mkdtemp(), "mime.types")
        hostile.write_text("text/plain\tjs\n", encoding="utf-8")
        raw_init = mimetypes.init.__wrapped__
        raw_init([str(hostile)])
        self.assertEqual(mimetypes.guess_type("f.js")[0], "text/plain")

    def test_repinning_is_installed_once(self):
        import mimetypes

        from odoo._monkeypatches.mimetypes import patch_module

        wrapper = mimetypes.init
        patch_module()
        self.assertIs(mimetypes.init, wrapper, "init() was wrapped a second time")


class TestCharsetLabels(unittest.TestCase):
    def test_separatorless_hebrew_variants_resolve(self):
        """Only the spellings `encodings.aliases` misses prove anything here.

        The table already carries `iso_8859_8_e` and `iso_8859_8_i`, so CPython
        resolves every hyphenated or underscored spelling unaided and an
        assertion about one would pass with the patch deleted.  The
        `assertNotIn` is what keeps this test from going vacuous if a future
        CPython adds them.
        """
        import codecs
        import encodings.aliases

        for label in ("iso88598i", "iso88598e", "iso8859_8_i"):
            with self.subTest(label=label):
                self.assertNotIn(
                    label,
                    encodings.aliases.aliases,
                    "CPython now aliases this itself; the assertion below no "
                    "longer measures the patch",
                )
                self.assertEqual(codecs.lookup(label).name, "iso8859-8")

    def test_the_spellings_cpython_already_handles_are_not_the_patch(self):
        """Guards the test above: these resolve with or without us."""
        import encodings.aliases

        for label in ("iso_8859_8_e", "iso_8859_8_i"):
            with self.subTest(label=label):
                self.assertIn(label, encodings.aliases.aliases)

    def test_an_unrelated_label_is_not_swallowed(self):
        import codecs

        with self.assertRaises(LookupError):
            codecs.lookup("iso88598ixxx")

    def test_thai_codepage_labels_resolve(self):
        import codecs

        for label in ("874", "windows-874"):
            with self.subTest(label=label):
                self.assertEqual(codecs.lookup(label).name, "cp874")


class TestBabelLocaleAlias(unittest.TestCase):
    def test_bare_nb_has_a_territory(self):
        """Request.best_lang maps a territory-less tag through LOCALE_ALIASES and
        turns the KeyError into "no language preference at all"."""
        import babel.core

        self.assertEqual(babel.core.LOCALE_ALIASES["nb"], "nb_NO")


class TestWerkzeugJsonModule(unittest.TestCase):
    def test_request_and_response_serialise_script_safely(self):
        from werkzeug.wrappers import Request, Response

        from odoo.libs.json import scriptsafe

        self.assertIs(Request.json_module, scriptsafe)
        self.assertIs(Response.json_module, scriptsafe)

    def test_multidict_deepcopy_still_tracks_the_memo(self):
        """A regression pin, vacuous by design: werkzeug 3.x gets this right.

        It fails only if someone re-adds the wrapper that dropped `memo`, which
        is what turned this into a RecursionError.
        """
        from werkzeug.datastructures import MultiDict

        multidict = MultiDict()
        box = {"multidict": multidict}
        multidict["back"] = box
        self.assertIsNotNone(copy.deepcopy(box))


class TestBulgarianIsRegistered(unittest.TestCase):
    """The patch's job is the registration; the language is tested in Tier 1.

    `odoo/libs/locale/tests/test_cardinals_bg.py` carries the grammar oracle
    and the invariant sweeps, DB-free and on every PR. What can only be
    asserted here is that the patch actually put the converter in num2words'
    registry, and that the fallback `res_currency.amount_to_text` depends on
    still works through the library's own entry point.
    """

    def test_num2words_dispatches_bg_to_our_converter(self):
        import num2words

        from odoo.libs.locale import BulgarianNumerals

        self.assertIsInstance(num2words.CONVERTER_CLASSES.get("bg"), BulgarianNumerals)

    def test_the_library_entry_point_reaches_it(self):
        """res_currency calls num2words(n, lang=...), not the class."""
        from num2words import num2words

        self.assertEqual(num2words(111, lang="bg"), "сто и единадесет")

    def test_an_unimplemented_form_raises_what_res_currency_catches(self):
        from num2words import num2words

        with self.assertRaises(NotImplementedError):
            num2words(7.5, lang="bg")


class TestFreezegunFacade(unittest.TestCase):
    """`odoo.tests.common` replaces `freezegun.freeze_time` process-wide.

    `from freezegun import freeze_time` therefore resolves to the wrapper in any
    module imported after `odoo.tests.common`, and to the real one otherwise --
    so a signature the wrapper does not accept is a `TypeError` that depends on
    import order. It used to drop three of freezegun's arguments.
    """

    def test_the_module_attribute_is_the_facade(self):
        import freezegun

        from odoo.tests.common import freeze_time

        self.assertIs(freezegun.freeze_time, freeze_time)

    def test_the_facade_accepts_every_argument_freezegun_does(self):
        import inspect

        import freezegun.api

        from odoo.tests.common import freeze_time

        theirs = set(inspect.signature(freezegun.api.freeze_time).parameters)
        ours = set(inspect.signature(freeze_time.__init__).parameters) - {"self"}
        self.assertFalse(
            theirs - ours,
            f"the facade drops {sorted(theirs - ours)}, so the same call is "
            f"valid or a TypeError depending on import order",
        )

    def test_a_dropped_argument_reaches_freezegun(self):
        """`ignore` is the one that was measured: passing it used to raise
        `TypeError: freeze_time.__init__() got an unexpected keyword argument`.

        Asserted on the freezer the facade built, not on a clock reading:
        freezegun resolves `ignore` against the whole call stack, and a test
        method is always reached through `unittest`, so any stack-based probe
        from in here reports the ignored answer whatever is passed.
        """
        from odoo.tests.common import freeze_time

        frozen = freeze_time("2020-01-01", ignore=["some.module"])
        self.assertIn("some.module", frozen.freezer.ignore)
