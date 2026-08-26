import logging
import os
from unittest.mock import patch

import pytest

from odoo.service import _env

VAR = "ODOO_TEST_ENV_KNOB"


@pytest.fixture
def _clean_env():
    with patch.dict(os.environ, clear=False):
        os.environ.pop(VAR, None)
        yield


# ---------------------------------------------------------------------------
# The contract env_float and env_int share
# ---------------------------------------------------------------------------

PARSERS = [
    pytest.param(_env.env_float, "45", 45.0, 30.0, id="env_float"),
    pytest.param(_env.env_int, "45", 45, 30, id="env_int"),
]


@pytest.mark.parametrize(("parse", "raw", "parsed", "default"), PARSERS)
class TestGuardedParserContract:
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
        with patch.dict(os.environ, {VAR: raw}):
            assert _env.env_float(VAR, 30.0) == 30.0

    def test_non_finite_is_refused_even_with_a_minimum(self):
        with patch.dict(os.environ, {VAR: "nan"}):
            assert _env.env_float(VAR, 30.0, minimum=0.1) == 30.0

    def test_warns_on_non_finite_when_logger_given(self):
        logger = logging.getLogger("odoo.service.test_env")
        with patch.dict(os.environ, {VAR: "inf"}):
            with patch.object(logger, "warning") as warn:
                assert _env.env_float(VAR, 30.0, logger=logger) == 30.0
        warn.assert_called_once()

    def test_non_finite_warning_does_not_double_the_article(self):
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
    def test_float_string_is_malformed(self):
        with patch.dict(os.environ, {VAR: "2.0"}):
            assert _env.env_int(VAR, 8) == 8
        with patch.dict(os.environ, {VAR: "2.0"}):
            assert _env.env_float(VAR, 8.0) == 2.0


# ---------------------------------------------------------------------------
# env_str
# ---------------------------------------------------------------------------


class TestEnvStr:
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
        os.environ[VAR] = raw
        assert _env.env_str(VAR, "fallback") == "fallback"
