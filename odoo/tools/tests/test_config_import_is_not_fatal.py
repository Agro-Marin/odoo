"""Importing ``odoo.tools`` must not be able to terminate the process.

``odoo/tools/__init__.py`` builds the singleton at module scope
(``config = configmanager()``), and that constructor reads ``$ODOO_*`` and the
rcfile and then *validates* the result. Validation there is fatal by
construction -- ``optparse.error()`` calls ``sys.exit(2)``, and a malformed env
value raises ``ValueError`` -- so ambient environment could kill any process
that imported the module, which ``odoo.orm``, ``odoo.db`` and ``odoo.http`` all
do transitively.

Measured before the fix, with ``ODOO_SYSLOG`` and ``ODOO_LOGFILE`` both set: the
whole Tier-1 pytest suite could not be **collected**, dying with

    __main__.py: error: the syslog and logfile options are exclusive

which names neither odoo nor the environment variable responsible. After it,
the same command collects 2684 tests.

The validation is not weakened, only moved to the call that means it:
``parse_config()`` re-runs the same parse over the same inputs, so a genuine
misconfiguration still fails there -- before the server starts, with the real
argv in the message. Construction populates; parsing validates.

Subprocesses throughout: the singleton is built once per interpreter, at import,
so the behaviour under a given environment is not observable in-process.
"""

import subprocess
import sys
import textwrap

#: Two options the parser rejects as mutually exclusive -- the combination that
#: was reported from the field, and the cheapest fatal path to reproduce.
_CONFLICTING = {"ODOO_SYSLOG": "1", "ODOO_LOGFILE": "/tmp/odoo-import-probe.log"}

#: A value the env loader cannot coerce, i.e. the ValueError path rather than
#: the SystemExit one. Both had to be caught; a test for only one would let the
#: other regress.
_MALFORMED = {"ODOO_LIMIT_TIME_CPU": "notanumber"}


def _run(code: str, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, **env_extra}
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,  # the return code IS the assertion
    )


def test_import_survives_conflicting_env_options():
    proc = _run("import odoo.tools; print('ALIVE')", _CONFLICTING)
    assert proc.returncode == 0, (
        f"`import odoo.tools` exited {proc.returncode} because of environment "
        f"variables. stderr:\n{proc.stderr}"
    )
    assert "ALIVE" in proc.stdout


def test_import_survives_a_malformed_env_value():
    proc = _run("import odoo.tools; print('ALIVE')", _MALFORMED)
    assert proc.returncode == 0, (
        f"`import odoo.tools` exited {proc.returncode} on a malformed env "
        f"value. stderr:\n{proc.stderr}"
    )
    assert "ALIVE" in proc.stdout


def test_import_is_quiet_about_it():
    """Swallowing the exit is not enough if the usage block still prints.

    optparse writes the message itself *before* calling ``sys.exit``, so an
    earlier version of this fix left every import printing a bare
    ``error: the syslog and logfile options are exclusive`` and then carrying
    on -- which reads as a failure that is not one, on every test run.
    """
    proc = _run("import odoo.tools", _CONFLICTING)
    assert "exclusive" not in proc.stderr, (
        f"import printed a parser error it then ignored:\n{proc.stderr}"
    )


def test_parse_config_still_rejects_the_same_environment():
    """The validation must be deferred, not deleted."""
    proc = _run(
        """
        from odoo.tools import config
        try:
            config.parse_config([], setup_logging=False)
        except (SystemExit, ValueError):
            print('REJECTED')
        else:
            print('ACCEPTED')
        """,
        _CONFLICTING,
    )
    assert "REJECTED" in proc.stdout, (
        "parse_config() accepted an environment the parser calls invalid; the "
        f"deferral above dropped the check instead of moving it.\n{proc.stdout}"
        f"\n{proc.stderr}"
    )


def test_a_clean_environment_still_populates_the_config():
    """Construction must still do its job on the ordinary path."""
    proc = _run(
        """
        from odoo.tools import config
        print('PORT', config['http_port'])
        """,
        {},
    )
    assert proc.returncode == 0, proc.stderr
    assert "PORT 8069" in proc.stdout, proc.stdout
