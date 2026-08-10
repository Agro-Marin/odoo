import subprocess
import sys
import textwrap

_CONFLICTING = {"ODOO_SYSLOG": "1", "ODOO_LOGFILE": "/tmp/odoo-import-probe.log"}

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
        check=False,
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
    proc = _run("import odoo.tools", _CONFLICTING)
    assert "exclusive" not in proc.stderr, (
        f"import printed a parser error it then ignored:\n{proc.stderr}"
    )


def test_parse_config_still_rejects_the_same_environment():
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
    proc = _run(
        """
        from odoo.tools import config
        print('PORT', config['http_port'])
        """,
        {},
    )
    assert proc.returncode == 0, proc.stderr
    assert "PORT 8069" in proc.stdout, proc.stdout
