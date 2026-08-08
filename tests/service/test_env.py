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
# env_float
# ---------------------------------------------------------------------------


class TestEnvFloat:
    @pytest.mark.usefixtures("_clean_env")
    def test_unset_returns_default(self):
        assert _env.env_float(VAR, 3600.0) == 3600.0

    def test_parses_valid_value(self):
        with patch.dict(os.environ, {VAR: "45"}):
            assert _env.env_float(VAR, 30.0) == 45.0

    def test_parses_float_string(self):
        with patch.dict(os.environ, {VAR: "0.25"}):
            assert _env.env_float(VAR, 30.0) == 0.25

    def test_malformed_falls_back_to_default(self):
        with patch.dict(os.environ, {VAR: "not-a-number"}):
            assert _env.env_float(VAR, 30.0) == 30.0

    def test_below_minimum_clamps(self):
        with patch.dict(os.environ, {VAR: "0.001"}):
            assert _env.env_float(VAR, 2.0, minimum=0.1) == 0.1

    def test_at_or_above_minimum_passes_through(self):
        with patch.dict(os.environ, {VAR: "5"}):
            assert _env.env_float(VAR, 2.0, minimum=0.1) == 5.0

    def test_negative_clamped_to_minimum(self):
        with patch.dict(os.environ, {VAR: "-3"}):
            assert _env.env_float(VAR, 2.0, minimum=0.1) == 0.1

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

    def test_warns_on_malformed_when_logger_given(self):
        logger = logging.getLogger("odoo.service.test_env")
        with patch.dict(os.environ, {VAR: "garbage"}):
            with patch.object(logger, "warning") as warn:
                assert _env.env_float(VAR, 30.0, logger=logger) == 30.0
        warn.assert_called_once()

    def test_silent_on_malformed_when_no_logger(self, caplog):
        """No logger argument means no record reaches logging at all.

        ``_env`` imports ``logging`` but deliberately keeps no module-level
        logger: it is imported by every ``odoo.service`` submodule, and a
        fallback ``_logger`` here would attribute the warning to ``_env``
        rather than to the module that owns the knob.  Asserting on the
        assignment alone would not notice one being added — this does.
        """
        with caplog.at_level(logging.DEBUG):
            with patch.dict(os.environ, {VAR: "garbage"}):
                assert _env.env_float(VAR, 30.0) == 30.0
        assert caplog.records == [], (
            f"env_float logged without being given a logger: {caplog.records!r}"
        )

    def test_warns_on_clamp_when_logger_given(self):
        logger = logging.getLogger("odoo.service.test_env")
        with patch.dict(os.environ, {VAR: "0.0"}):
            with patch.object(logger, "warning") as warn:
                assert _env.env_float(VAR, 2.0, minimum=0.1, logger=logger) == 0.1
        warn.assert_called_once()


# ---------------------------------------------------------------------------
# env_int
# ---------------------------------------------------------------------------


class TestEnvInt:
    @pytest.mark.usefixtures("_clean_env")
    def test_unset_returns_default(self):
        assert _env.env_int(VAR, 8) == 8

    def test_parses_valid_value(self):
        with patch.dict(os.environ, {VAR: "12"}):
            assert _env.env_int(VAR, 8) == 12

    def test_zero_is_preserved(self):
        # "0" is a meaningful opt-out for ODOO_MAX_HTTP_THREADS — must not be
        # treated as falsy-and-replaced by the parser.
        with patch.dict(os.environ, {VAR: "0"}):
            assert _env.env_int(VAR, 8) == 0

    def test_float_string_is_malformed(self):
        # int("2.0") raises ValueError -> default (no implicit truncation),
        # matching the historical ``int(os.environ[...])`` call sites.
        with patch.dict(os.environ, {VAR: "2.0"}):
            assert _env.env_int(VAR, 8) == 8

    def test_malformed_falls_back_to_default(self):
        with patch.dict(os.environ, {VAR: "not-a-number"}):
            assert _env.env_int(VAR, 8) == 8

    def test_below_minimum_clamps_up(self):
        # ODOO_ADMIN_PASSWORD_MIN_LENGTH semantics: env can only RAISE the floor.
        with patch.dict(os.environ, {VAR: "4"}):
            assert _env.env_int(VAR, 8, minimum=8) == 8

    def test_above_minimum_passes_through(self):
        with patch.dict(os.environ, {VAR: "12"}):
            assert _env.env_int(VAR, 8, minimum=8) == 12


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
