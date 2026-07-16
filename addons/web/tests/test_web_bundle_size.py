"""Bundle-size regression tests for ESM bundles.

Each test pins an upper-bound byte budget for a key bundle, so a
regression (heavy dependency added, forgot to lazy-load, wildcard
glob pulled in too much, un-tree-shaken dead code) is caught at PR
time instead of showing up later in production CWV telemetry from
``services/web_vitals/web_vitals_service.js``.

Budgets are hardcoded inline (mirroring ``test_web_perf_regression.py``'s
convention for query counts) rather than externalized to JSON: bumping
one should be a deliberate review event with justification in the
commit message.

Calibration workflow when adding a new bundle target:

  1. Add the bundle to ``BUDGETS`` with a placeholder large enough not
     to fail (e.g. ``10_000_000``).
  2. Run the test:

         > ./odoo.log && ./core/odoo-bin -c ./conf/odoo.conf -d $DB \\
             --test-tags '/web:TestWebBundleSize' -u web \\
             --stop-after-init --workers=0
         grep '\\[BUNDLE_SIZE\\]' ./odoo.log

  3. Read the ``actual`` byte count from the log line and tighten the
     budget to ``actual + ~10%`` headroom.

A failing test's message names the bundle, the actual bytes, the
budget, and the delta.

PER-INPUT DIAGNOSTIC
--------------------
On budget failure, the test parses the ``EsbuildResult.metafile`` field
(esbuild's JSON output describing per-input contributions) and prints
the top-N contributing files. With a baseline file
(``tooling/scripts/bundle_size_inputs_baseline.json``) present, it
shows deltas against that baseline instead of absolute sizes.

To populate / refresh the per-input baseline::

  ODOO_BUNDLE_SIZE_UPDATE_BASELINE=1 ./core/odoo-bin \\
      -c ./conf/odoo.conf -d $DB \\
      --test-tags '/web:TestWebBundleSize' -u web \\
      --stop-after-init --workers=0

In that mode each test writes its current per-input map into the
baseline JSON instead of asserting against the budget. Commit the
regenerated baseline alongside any PR that bumps ``BUDGETS``.
"""

import json
import logging
import os
from datetime import date
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)

# Optional: when absent, diagnostics fall back to top-N absolute contributors.
_BASELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tooling"
    / "scripts"
    / "bundle_size_inputs_baseline.json"
)

_DIAGNOSTIC_TOP_N = 10

_UPDATE_ENV_VAR = "ODOO_BUNDLE_SIZE_UPDATE_BASELINE"


@tagged(
    "post_install",
    "-at_install",
    "web_perf",
    "web_assets",
    "web_bundle_size",
)
class TestWebBundleSize(TransactionCase):
    """Pin upper-bound byte sizes for ESM bundles to catch regressions."""

    # Calibrated 2026-05-10 against the marin190 database (see module
    # docstring for the calibration workflow). Bump entries here when
    # intentional growth lands; leave them as-is otherwise so accidental
    # regressions trip the test.
    BUDGETS = {
        # Primary backend entry — every backend page load pays this
        # bundle's TTI cost. 2026-05-13 actual: 3,940,406 bytes.
        # Recalibrated after web/mail/html_editor IMP wave landed
        # between 2026-05-10 and 2026-05-13 (FullCalendar v7 RC,
        # useRenderCounter, aria-live, RPC dedup, save coordinator
        # guards, ControllerComponent decomposition). Top contributors
        # remain pre-existing heavy files (emoji_data 461 KB, odoo_sfu
        # 232 KB) inlined because esbuild here runs without
        # ``--splitting``; per-view code-splitting is tracked as the
        # long-term fix (see ``machine_doc_v1/ARCHITECTURE.md``).
        "web.assets_web": 4_335_000,
        # Public-facing bundle — mobile + cold-cache visitors,
        # higher cost-per-byte than backend. 2026-05-10 actual:
        # 1,311,942 bytes.
        "web.assets_frontend": 1_445_000,
        # Extended frontend bundle — full set of public components.
        # Loaded after assets_frontend; cumulative cost matters for
        # public-page UX. 2026-05-10 actual: 1,311,064 bytes.
        "web.assets_frontend_lazy": 1_445_000,
        # Emoji data shipped lazily by the emoji picker. Sole content
        # is `emoji_data.js` (~36k lines of generated emoji metadata);
        # bytes matter because every chat / textarea / mail composer
        # triggers a load. 2026-05-10 actual: 464,735 bytes.
        "web.assets_emoji": 515_000,
        # Minimal bootstrap bundle — session.js + cookie + minimal DOM
        # + lazyloader. First JS every public visitor sees; LCP-critical
        # on cold cache. 2026-05-10 actual: 6,270 bytes. Tight budget
        # is intentional: this bundle should NEVER grow significantly,
        # any growth here is a real regression to investigate.
        "web.assets_frontend_minimal": 7_000,
        # CANARY (not a user-perf budget): dark-mode bundle ships only
        # CSS to users (template uses ``t-js="false"``). The ~2.83 MB
        # of JS that esbuild produces here is build artifact and never
        # reaches a browser — it exists because the manifest does
        # ``("include", "web.assets_web")`` to inherit SCSS variable
        # scope, and the include pulls JS along for the ride. Budget
        # pinned at assets_web's footprint catches the case where a
        # future change accidentally adds JS contributions unique to
        # the dark bundle (which would be wrong — dark only ships CSS).
        # 2026-05-13 actual: 3,940,406 bytes (recalibrated with
        # assets_web; canary tracks the parent bundle's footprint).
        #
        # Stripping the JS via ``("remove", "web/static/**/*.js")`` was
        # attempted and reverted: the asset pipeline's REMOVE directive
        # resolves globs against the filesystem, then requires every
        # matched file to be in the bundle — too strict for a "strip
        # all JS" use case. The cleanest path forward is restructuring
        # ``web._assets_core`` (currently mixed JS+SCSS) into a parallel
        # ``web._assets_core_scss`` sub-bundle so dark/print can inherit
        # SCSS variable scope without the JS payload. Tracked as future
        # work; not blocking.
        "web.assets_web_dark": 4_335_000,
        # CANARY: same shape as assets_web_dark — print bundle ships
        # only CSS (webclient_templates.xml loads it with
        # ``t-js="false"``). Build-only JS, pinned to assets_web's
        # footprint to catch unexpected JS contributions.
        # 2026-05-13 actual: 3,939,148 bytes (recalibrated with
        # assets_web; canary tracks the parent bundle's footprint).
        "web.assets_web_print": 4_335_000,
        # Common report assets — loaded for every PDF/HTML report
        # render. Regression here slows every printout. 2026-05-10
        # actual: 88,046 bytes.
        "web.report_assets_common": 97_000,
        # PDF-specific report assets — extends report_assets_common
        # for PDF-only renders. Currently skipped on this install
        # (no native modules); the budget caps the upper bound when
        # PDF-bundle JS contributions appear in a richer install.
        "web.report_assets_pdf": 1_000_000,
    }

    @staticmethod
    def _parse_metafile_inputs(metafile_raw):
        """Extract ``{input_path: bytes_in_output}`` from esbuild's metafile.

        The metafile has shape ``{outputs: {<out_path>: {inputs:
        {<in_path>: {bytesInOutput: N}}}}}``.  Each output entry can
        be a ``.js`` (the bundle) or ``.js.map`` (sourcemap); only
        the ``.js`` output contributes meaningful per-input bytes.

        Returns ``{}`` if the metafile is missing or malformed — the
        diagnostic is non-fatal and should never break a budget check.

        Static because it touches neither ``self`` nor ``env`` — and
        the unit-test class exercises it directly via
        ``TestWebBundleSize._parse_metafile_inputs(...)`` without
        instantiating a budget test.

        :param str|None metafile_raw: the ``metafile`` field of the
            ``EsbuildResult`` returned by ``esbuild_native_bundle()``
        :rtype: dict[str, int]
        """
        if not metafile_raw:
            return {}
        try:
            metafile = json.loads(metafile_raw)
        except ValueError, TypeError:
            return {}
        inputs = {}
        for out_path, out_info in metafile.get("outputs", {}).items():
            if not out_path.endswith(".js"):
                continue
            for in_path, contrib in out_info.get("inputs", {}).items():
                inputs[in_path] = inputs.get(in_path, 0) + int(
                    contrib.get("bytesInOutput", 0),
                )
        return inputs

    def _measure_esm_bundle_bytes(self, bundle_name):
        """Trigger esbuild for the bundle; return total bytes + per-input map.

        Calls ``esbuild_native_bundle()`` directly to measure a fresh
        build — bypassing any cached ``ir.attachment`` so a stale
        attachment cannot mask a regression.

        :param str bundle_name: bundle key from a module manifest's
            ``assets`` dict (e.g. ``"web.assets_web"``)
        :return: ``(output_bytes, inputs_map)`` where ``inputs_map``
            is ``{input_path: bytes_in_output}`` parsed from the
            metafile sidecar; empty when the metafile is unavailable
        :rtype: tuple[int, dict[str, int]]
        """
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            bundle_name,
            css=False,
            js=True,
        )
        if not bundle.native_modules:
            # Some bundles' contents depend on which addons are
            # installed (e.g. ``assets_inside_builder_iframe`` only
            # has content when website/web_studio is around).  Skip
            # rather than fail so the test stays useful across
            # different installations: a regression in a sibling
            # bundle still trips its own assertion, and a bundle that
            # shows up on a richer install will get measured there.
            self.skipTest(
                f"Bundle {bundle_name!r} has no native modules in "
                f"this installation; nothing to measure."
            )
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            result = bundle.esbuild_native_bundle()
        return (
            len(result.code.encode("utf-8")),
            self._parse_metafile_inputs(result.metafile),
        )

    def _load_baseline(self):
        """Read the per-input baseline JSON if present.

        :rtype: dict — the full baseline document, or ``{}`` when
            the file is missing or unreadable.  Callers must defensively
            ``.get("bundles", {}).get(name, {}).get("inputs", {})``.
        """
        if not _BASELINE_PATH.exists():
            return {}
        try:
            return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
        except ValueError, OSError:
            return {}

    def _save_baseline_entry(self, bundle_name, total_bytes, inputs_map):
        """Update the baseline JSON in place with one bundle's data.

        Sorts keys for stable diffs (so PR review sees real changes,
        not key reshuffling).  Creates the parent directory if needed.
        """
        baseline = self._load_baseline()
        baseline["_generated_at"] = date.today().isoformat()
        baseline["_generator"] = f"test_web_bundle_size.py with {_UPDATE_ENV_VAR}=1"
        bundles = baseline.setdefault("bundles", {})
        bundles[bundle_name] = {
            "_total_bytes": total_bytes,
            "inputs": dict(sorted(inputs_map.items())),
        }
        # Sort top-level bundle keys too for stable output.
        baseline["bundles"] = dict(sorted(bundles.items()))
        _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BASELINE_PATH.write_text(
            json.dumps(baseline, indent=2) + "\n",
            encoding="utf-8",
        )

    def _build_diagnostic(self, bundle_name, inputs_map):
        """Return the per-input diagnostic block for a failure message.

        With a baseline: shows top-N grown inputs (``delta = current -
        baseline``, sorted descending), each line ``+N b   path
        (base → cur)``.

        Without a baseline: shows top-N absolute contributors with a
        hint to populate the baseline.

        Empty/missing metafile: brief notice that no breakdown is
        available — does not raise.
        """
        if not inputs_map:
            return "  (esbuild metafile unavailable — no per-input breakdown)"

        baseline = self._load_baseline()
        bundle_baseline = (
            baseline.get("bundles", {}).get(bundle_name, {}).get("inputs", {})
        )

        if bundle_baseline:
            deltas = []
            for path, cur in inputs_map.items():
                base = bundle_baseline.get(path, 0)
                if cur > base:
                    deltas.append((path, base, cur, cur - base))
            deltas.sort(key=lambda t: -t[3])
            if not deltas:
                # Bundle grew but no per-input regressed — likely a
                # new input that the baseline doesn't yet know about.
                new_inputs = [
                    (p, b) for p, b in inputs_map.items() if p not in bundle_baseline
                ]
                new_inputs.sort(key=lambda kv: -kv[1])
                if not new_inputs:
                    return (
                        "  (no per-input growth detected against baseline — "
                        "regression may be in entry-glue overhead, not file content)"
                    )
                lines = [
                    "  No grown inputs vs baseline — "
                    "regression appears to be NEW inputs:",
                    *(
                        f"    {bytes_:>10,} b   {path} (new)"
                        for path, bytes_ in new_inputs[:_DIAGNOSTIC_TOP_N]
                    ),
                ]
                return "\n".join(lines)
            lines = [
                "  Top contributors to growth (vs baseline):",
                *(
                    f"    +{delta:>9,} b   {path}  ({base:,} → {cur:,})"
                    for path, base, cur, delta in deltas[:_DIAGNOSTIC_TOP_N]
                ),
            ]
            return "\n".join(lines)

        top = sorted(inputs_map.items(), key=lambda kv: -kv[1])[:_DIAGNOSTIC_TOP_N]
        lines = [
            "  Top contributors to bundle (no baseline available):",
            *(f"    {bytes_:>10,} b   {path}" for path, bytes_ in top),
            f"  Run with {_UPDATE_ENV_VAR}=1 to populate the baseline",
            "  so future failures show deltas instead of absolute sizes.",
        ]
        return "\n".join(lines)

    def _assert_bundle_under_budget(self, bundle_name):
        """Measure the bundle and assert it stays within ``BUDGETS``.

        Logs an ``[BUNDLE_SIZE]`` line on every run (pass or fail) so
        operators can monitor headroom drift without waiting for a
        failure.

        When ``ODOO_BUNDLE_SIZE_UPDATE_BASELINE=1``: regenerates the
        per-input baseline for this bundle instead of asserting.
        Used to refresh the baseline after an approved size change.

        :param str bundle_name: bundle key from ``BUDGETS``
        """
        budget = self.BUDGETS.get(bundle_name)
        if budget is None:
            self.fail(
                f"No budget defined for {bundle_name!r}. Add an entry "
                f"to TestWebBundleSize.BUDGETS — see the module "
                f"docstring for the calibration workflow."
            )
        actual, inputs_map = self._measure_esm_bundle_bytes(bundle_name)

        if os.environ.get(_UPDATE_ENV_VAR):
            self._save_baseline_entry(bundle_name, actual, inputs_map)
            _logger.info(
                "[BUNDLE_SIZE] baseline-update bundle=%s total=%d inputs=%d",
                bundle_name,
                actual,
                len(inputs_map),
            )
            return

        headroom = budget - actual
        headroom_pct = headroom * 100 / budget if budget else 0
        _logger.info(
            "[BUNDLE_SIZE] bundle=%s actual=%d budget=%d headroom=%d (%.1f%%)",
            bundle_name,
            actual,
            budget,
            headroom,
            headroom_pct,
        )

        if actual <= budget:
            return

        diagnostic = self._build_diagnostic(bundle_name, inputs_map)
        self.fail(
            f"Bundle {bundle_name!r} esbuild output is {actual:,} bytes, "
            f"exceeding budget of {budget:,} bytes "
            f"(+{actual - budget:,} = +{(actual - budget) * 100 / budget:.1f}%). "
            f"Either trim the regression that added bytes, or bump the "
            f"BUDGETS entry in this test with justification in the "
            f"commit message.\n"
            f"{diagnostic}"
        )

    def test_assets_web_under_budget(self):
        """``web.assets_web`` — full backend entry, TTI-critical.

        Regressions here delay every backend page load. Common
        regression sources: heavy dependency added to a glob-included
        directory (``views/**/*``, ``fields/**/*``); a ``remove``
        directive accidentally dropped from ``__manifest__.py``;
        un-tree-shaken dead code in a new feature.
        """
        self._assert_bundle_under_budget("web.assets_web")

    def test_assets_frontend_under_budget(self):
        """``web.assets_frontend`` — public pages, mobile-critical.

        Public-facing perf has higher stakes than backend: cold
        visitors with no warm cache, often on mobile networks.
        Anything imported from a backend-only widget that leaks here
        is a regression.
        """
        self._assert_bundle_under_budget("web.assets_frontend")

    def test_assets_frontend_lazy_under_budget(self):
        """``web.assets_frontend_lazy`` — extended frontend bundle.

        Loaded after ``assets_frontend`` to bring in the full set of
        public components. Cumulative public-facing cost: this bundle
        plus its parent. Leaks of backend-only code into this bundle
        bloat every public visitor's session.
        """
        self._assert_bundle_under_budget("web.assets_frontend_lazy")

    def test_assets_emoji_under_budget(self):
        """``web.assets_emoji`` — lazy emoji picker data.

        Single-file bundle (``emoji_data.js``, ~36k generated lines).
        Bytes matter because every chat textarea / mail composer
        triggers a load. Watch for: emoji-data regenerator producing
        bigger output (new Unicode versions, extra metadata fields).
        """
        self._assert_bundle_under_budget("web.assets_emoji")

    def test_assets_frontend_minimal_under_budget(self):
        """``web.assets_frontend_minimal`` — bootstrap JS for public pages.

        First JS every public visitor sees (session bootstrap, cookie
        handling, minimal DOM helpers, lazyloader). Cold-cache LCP-
        critical: even small regressions here delay first paint on
        every public page. Watch for: anything that imports a heavy
        utility module from the broader frontend bundle.
        """
        self._assert_bundle_under_budget("web.assets_frontend_minimal")

    def test_assets_web_dark_under_budget(self):
        """``web.assets_web_dark`` — CANARY for build-only JS.

        None of this bundle's JS ships to users (see the ``BUDGETS``
        entry for why). If this fails, the right fix is almost always
        "remove the JS contribution", not "raise the budget".
        """
        self._assert_bundle_under_budget("web.assets_web_dark")

    def test_assets_web_print_under_budget(self):
        """``web.assets_web_print`` — CANARY for build-only JS.

        Same shape as ``test_assets_web_dark_under_budget``; see the
        ``BUDGETS`` entry for why this bundle's JS never reaches users.
        """
        self._assert_bundle_under_budget("web.assets_web_print")

    def test_report_assets_common_under_budget(self):
        """``web.report_assets_common`` — common report assets.

        Loaded for every HTML/PDF report render. Regressions here
        slow every printout (and every PDF-render-via-headless path
        used by the chrome PDF subprocess).
        """
        self._assert_bundle_under_budget("web.report_assets_common")

    def test_report_assets_pdf_under_budget(self):
        """``web.report_assets_pdf`` — PDF-specific report assets.

        Extends ``report_assets_common`` for PDF-only renders. Heavy
        bundles here directly inflate every chrome-rendered PDF's
        prep time.
        """
        self._assert_bundle_under_budget("web.report_assets_pdf")


@tagged("web_unit", "web_assets", "web_bundle_size")
class TestParseMetafileInputs(TransactionCase):
    """Unit coverage for the metafile-parsing helper used by the diagnostic.

    These tests don't invoke esbuild — they feed hand-crafted metafile
    JSON to ``_parse_metafile_inputs`` so the parsing path can be
    exercised quickly (web_unit, ~1 ms each) without paying the cost
    of a real bundle build.

    The helper is a ``@staticmethod`` on ``TestWebBundleSize`` so we
    can call it directly without instantiating that class (which would
    require a valid budget-test method name in its ``__init__``).
    """

    _parse = staticmethod(TestWebBundleSize._parse_metafile_inputs)

    def test_none_returns_empty(self):
        self.assertEqual(self._parse(None), {})

    def test_empty_string_returns_empty(self):
        self.assertEqual(self._parse(""), {})

    def test_malformed_json_returns_empty(self):
        # Defensive: never let a diagnostic helper crash the budget check.
        self.assertEqual(self._parse("not-json"), {})
        self.assertEqual(self._parse("{partial"), {})

    def test_well_formed_metafile_extracts_inputs(self):
        meta = json.dumps(
            {
                "outputs": {
                    "/tmp/x.js": {
                        "inputs": {
                            "addons/web/static/src/a.js": {"bytesInOutput": 100},
                            "addons/web/static/src/b.js": {"bytesInOutput": 200},
                        },
                        "bytes": 5000,
                    },
                },
            }
        )
        self.assertEqual(
            self._parse(meta),
            {
                "addons/web/static/src/a.js": 100,
                "addons/web/static/src/b.js": 200,
            },
        )

    def test_sourcemap_output_is_skipped(self):
        # Only ``.js`` outputs contribute meaningful per-input bytes;
        # ``.js.map`` entries should be ignored so input bytes aren't
        # double-counted across map+bundle.
        meta = json.dumps(
            {
                "outputs": {
                    "/tmp/x.js": {
                        "inputs": {"a.js": {"bytesInOutput": 100}},
                    },
                    "/tmp/x.js.map": {
                        "inputs": {"a.js": {"bytesInOutput": 50}},
                    },
                },
            }
        )
        self.assertEqual(self._parse(meta), {"a.js": 100})

    def test_missing_outputs_key_returns_empty(self):
        # Defensive: shape might drift in a future esbuild release; an
        # incomplete metafile must not crash the diagnostic.
        self.assertEqual(self._parse(json.dumps({})), {})
        self.assertEqual(self._parse(json.dumps({"outputs": {}})), {})

    def test_missing_bytes_in_output_treated_as_zero(self):
        meta = json.dumps(
            {
                "outputs": {
                    "/tmp/x.js": {
                        "inputs": {
                            "a.js": {},
                            "b.js": {"bytesInOutput": 50},
                        },
                    },
                },
            }
        )
        self.assertEqual(self._parse(meta), {"a.js": 0, "b.js": 50})
