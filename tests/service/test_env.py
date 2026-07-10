"""Pure-pytest tests for ``odoo.service._env``.

The guarded env-var parsers (``env_float`` / ``env_int``) that every
``odoo.service`` submodule routes its ``ODOO_*`` numeric knobs through.  No
DB, no Odoo import chain — the module depends only on ``os`` and ``logging``.

Run with::

    python -m pytest tests/service/test_env.py -v
"""

import logging
import os
from unittest.mock import patch

import pytest

from odoo.service import _env

VAR = "ODOO_TEST_ENV_KNOB"


@pytest.fixture()
def _clean_env():
    """Ensure ``VAR`` is absent, restoring the environment afterwards."""
    with patch.dict(os.environ, clear=False):
        os.environ.pop(VAR, None)
        yield


# ---------------------------------------------------------------------------
# env_float
# ---------------------------------------------------------------------------


class TestEnvFloat:
    def test_unset_returns_default(self, _clean_env):
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

    def test_warns_on_malformed_when_logger_given(self):
        logger = logging.getLogger("odoo.service.test_env")
        with patch.dict(os.environ, {VAR: "garbage"}):
            with patch.object(logger, "warning") as warn:
                assert _env.env_float(VAR, 30.0, logger=logger) == 30.0
        warn.assert_called_once()

    def test_silent_on_malformed_when_no_logger(self):
        # No logger -> no warning is emitted (cannot patch a None logger;
        # the contract is simply that the value falls back without raising).
        with patch.dict(os.environ, {VAR: "garbage"}):
            assert _env.env_float(VAR, 30.0) == 30.0

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
    def test_unset_returns_default(self, _clean_env):
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
