"""Pure-pytest tests for ``odoo.service._env``.

The guarded env-var parsers (``env_float`` / ``env_int`` / ``env_str``) that
every ``odoo.service`` submodule routes its ``ODOO_*`` knobs through.  No DB, no
Odoo import chain — the module depends only on ``os``, ``math`` and ``logging``.

Run with::

    python -m pytest tests/service/test_env.py -v
"""

import logging
import os
from unittest.mock import patch

import pytest

from odoo.service import _env

VAR = "ODOO_TEST_ENV_KNOB"


@pytest.fixture
def _clean_env():
    """Ensure ``VAR`` is absent, restoring the environment afterwards."""
    with patch.dict(os.environ, clear=False):
        os.environ.pop(VAR, None)
        yield


# ---------------------------------------------------------------------------
# The contract env_float and env_int share
# ---------------------------------------------------------------------------

#: Both public parsers are thin wrappers over one ``_env._parse``, so every rule
#: below holds for both by construction — and used to be asserted for one.
#: ``TestEnvInt`` carried none of the four logger cases ``TestEnvFloat`` did, and
#: the two sets could drift without either failing.  Each entry is
#: ``(parser, a valid raw value, its parsed form, a default)``.
PARSERS = [
    pytest.param(_env.env_float, "45", 45.0, 30.0, id="env_float"),
    pytest.param(_env.env_int, "45", 45, 30, id="env_int"),
]


@pytest.mark.parametrize(("parse", "raw", "parsed", "default"), PARSERS)
class TestGuardedParserContract:
    """What every ``ODOO_*`` knob gets, whichever parser reads it."""

    @pytest.mark.usefixtures("_clean_env")
    def test_unset_returns_default(self, parse, raw, parsed, default):
        assert parse(VAR, default) == default

    def test_parses_a_valid_value(self, parse, raw, parsed, default):
        with patch.dict(os.environ, {VAR: raw}):
            assert parse(VAR, default) == parsed

    def test_malformed_falls_back_to_default(self, parse, raw, parsed, default):
        with patch.dict(os.environ, {VAR: "not-a-number"}):
            assert parse(VAR, default) == default

    def test_below_minimum_clamps_up(self, parse, raw, parsed, default):
        with patch.dict(os.environ, {VAR: "1"}):
            assert parse(VAR, default, minimum=8) == 8

    def test_at_or_above_minimum_passes_through(self, parse, raw, parsed, default):
        with patch.dict(os.environ, {VAR: raw}):
            assert parse(VAR, default, minimum=8) == parsed

    def test_negative_clamps_to_minimum(self, parse, raw, parsed, default):
        with patch.dict(os.environ, {VAR: "-3"}):
            assert parse(VAR, default, minimum=8) == 8

    def test_zero_is_preserved(self, parse, raw, parsed, default):
        """``0`` is a meaningful opt-out for several knobs (``ODOO_MAX_HTTP_
        THREADS``, ``limit_time_cpu``) and must not be treated as falsy-and-
        replaced."""
        with patch.dict(os.environ, {VAR: "0"}):
            assert parse(VAR, default) == 0

    def test_warns_on_malformed_when_a_logger_is_given(
        self, parse, raw, parsed, default
    ):
        logger = logging.getLogger("odoo.service.test_env")
        with patch.dict(os.environ, {VAR: "garbage"}):
            with patch.object(logger, "warning") as warn:
                assert parse(VAR, default, logger=logger) == default
        warn.assert_called_once()

    def test_warns_on_clamp_when_a_logger_is_given(self, parse, raw, parsed, default):
        logger = logging.getLogger("odoo.service.test_env")
        with patch.dict(os.environ, {VAR: "1"}):
            with patch.object(logger, "warning") as warn:
                assert parse(VAR, default, minimum=8, logger=logger) == 8
        warn.assert_called_once()

    def test_silent_when_no_logger_is_given(self, parse, raw, parsed, default, caplog):
        """No logger argument means no record reaches logging at all.

        ``_env`` imports ``logging`` but deliberately keeps no module-level
        logger: it is imported by every ``odoo.service`` submodule, and a
        fallback ``_logger`` here would attribute the warning to ``_env`` rather
        than to the module that owns the knob.  Asserting on the assignment alone
        would not notice one being added — this does.
        """
        with caplog.at_level(logging.DEBUG):
            with patch.dict(os.environ, {VAR: "garbage"}):
                assert parse(VAR, default) == default
        assert caplog.records == [], (
            f"{parse.__name__} logged without being given a logger: {caplog.records!r}"
        )


# ---------------------------------------------------------------------------
# env_float — what is specific to parsing a float
# ---------------------------------------------------------------------------


class TestEnvFloat:
    def test_parses_float_string(self):
        with patch.dict(os.environ, {VAR: "0.25"}):
            assert _env.env_float(VAR, 30.0) == 0.25

    @pytest.mark.parametrize(
        "raw", ["inf", "-inf", "Infinity", "nan", "NaN", "1e400", "-1e400"]
    )
    def test_non_finite_falls_back_to_default(self, raw):
        """``float()`` ACCEPTS these, so they slip past the malformed check.

        This is the one branch of ``env_float`` no test reached (verified by
        mutation: deleting the ``math.isfinite`` guard left the whole 760-test
        suite green), and it is the branch that matters most.  Every stall
        timeout in this package is armed from ``env_float``, so
        ``ODOO_PG_DUMP_TOTAL_TIMEOUT=inf`` would build a
        ``threading.Timer(inf)`` — silently disarming the wall-clock ceiling
        that ``TestDumpDbWallClockTimeout`` exists to enforce, without ever
        looking malformed.  ``1e400`` is the same hole reached through a
        literal that overflows to ``inf`` rather than spelling it.

        ``nan`` is worse than useless rather than merely unbounded: every
        comparison against it is ``False``, so a ``minimum=`` clamp would pass
        it straight through.
        """
        with patch.dict(os.environ, {VAR: raw}):
            assert _env.env_float(VAR, 30.0) == 30.0

    def test_non_finite_is_refused_even_with_a_minimum(self):
        """The clamp cannot rescue ``nan``: ``nan < minimum`` is ``False``, so
        without the finite check it would be returned as the live value."""
        with patch.dict(os.environ, {VAR: "nan"}):
            assert _env.env_float(VAR, 30.0, minimum=0.1) == 30.0

    def test_warns_on_non_finite_when_logger_given(self):
        logger = logging.getLogger("odoo.service.test_env")
        with patch.dict(os.environ, {VAR: "inf"}):
            with patch.object(logger, "warning") as warn:
                assert _env.env_float(VAR, 30.0, logger=logger) == 30.0
        warn.assert_called_once()

    def test_non_finite_warning_does_not_double_the_article(self):
        """``label`` is "a number" / "an integer" — article included — so the
        non-finite branch cannot reuse the malformed template without emitting
        "is not a finite a number"."""
        logger = logging.getLogger("odoo.service.test_env")
        with patch.dict(os.environ, {VAR: "nan"}):
            with patch.object(logger, "warning") as warn:
                assert _env.env_float(VAR, 1.5, logger=logger) == 1.5
        rendered = warn.call_args.args[0] % warn.call_args.args[1:]
        assert rendered == f"{VAR}='nan' is not finite; using default 1.5"


# ---------------------------------------------------------------------------
# env_int
# ---------------------------------------------------------------------------


class TestEnvInt:
    """Only what differs from the shared contract above."""

    def test_float_string_is_malformed(self):
        # int("2.0") raises ValueError -> default (no implicit truncation),
        # matching the historical ``int(os.environ[...])`` call sites. The float
        # parser accepts the same string, which is the whole difference.
        with patch.dict(os.environ, {VAR: "2.0"}):
            assert _env.env_int(VAR, 8) == 8
        with patch.dict(os.environ, {VAR: "2.0"}):
            assert _env.env_float(VAR, 8.0) == 2.0


# ---------------------------------------------------------------------------
# env_str
# ---------------------------------------------------------------------------


class TestEnvStr:
    """``env_str`` is the third member of this trio and belongs beside them.

    It lived in ``test_metrics.py`` because its first caller was the metrics
    endpoint's auth token — but the parser is not a metrics concern, and
    splitting the three left ``env_str`` out of every check applied to
    ``env_float`` / ``env_int``.  The blank-is-unset rule is a security
    property wherever it is used: ``ODOO_METRICS_TOKEN="   "`` must read as
    "no token configured", i.e. endpoint disabled, not as a token of spaces
    that a caller could match.

    (That knob is read in ``addons/web/controllers/home.py`` and its endpoint
    behaviour is covered by ``addons/web/tests/test_health.py``; this file owns
    only the parser.  The name here previously read ``ODOO_PROMETHEUS_TOKEN``,
    which exists nowhere in the workspace.)
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, ""),
            ("", ""),
            ("   ", ""),
            ("\t\n", ""),
            ("  tok  ", "tok"),
            ("tok", "tok"),
        ],
    )
    @pytest.mark.usefixtures("_clean_env")
    def test_blank_is_treated_as_unset(self, raw, expected):
        if raw is not None:
            os.environ[VAR] = raw
        assert _env.env_str(VAR) == expected

    @pytest.mark.usefixtures("_clean_env")
    def test_default_is_returned_when_unset(self):
        assert _env.env_str(VAR, "fallback") == "fallback"

    @pytest.mark.parametrize("raw", ["", "   "])
    @pytest.mark.usefixtures("_clean_env")
    def test_blank_does_not_shadow_the_default(self, raw):
        """Blank means unset, so the DEFAULT must win — not the empty string."""
        os.environ[VAR] = raw
        assert _env.env_str(VAR, "fallback") == "fallback"
