"""What ``list_dbs`` actually exposes, against a real ``pg_database``.

``list_dbs`` answers the unauthenticated ``list`` verb (``/jsonrpc``,
``/xmlrpc/2/db``, and the database-manager wizard), so its ``WHERE`` clause is
the boundary between "databases this instance serves" and "every database on the
cluster".  It carries four filters, and each one is a decision:

* ``datdba = (SELECT usesysid FROM pg_user WHERE usename = current_user)`` —
  ownership.  On a shared cluster this is the only thing keeping another
  tenant's database names off an anonymous RPC response.
* ``NOT datistemplate`` and ``datallowconn`` — a template or a
  connections-disabled database can never be served, so offering it is a lie
  that ends in a failed connect.
* ``datname != ALL(%s)`` — ``postgres`` and the configured ``db_template``.

The DB-free suite covers only the branches that return BEFORE this query: the
``AccessDenied`` raise and the ``db_name``/``dbfilter`` shortcut.  The query
itself was reached by no test at any tier, and it cannot be tested by a mock —
a stubbed cursor returns whatever the stub was told to return, which is the
belief under test.  So it is measured here against a real cluster.

Assertions are CONTAINMENT, never an exact list: this suite runs against a
developer's cluster where other sessions hold scratch databases the connecting
role also owns, and an exact-match test would fail for reasons that have nothing
to do with the filter.
"""

import subprocess
import uuid

import pytest

from .conftest import requires_pg


def _psql(sql: str, dbname: str = "postgres") -> str:
    proc = subprocess.run(
        ["psql", "-d", dbname, "-X", "-tAc", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _drop(name: str) -> None:
    """Drop a database that may be a template and may refuse connections."""
    subprocess.run(
        [
            "psql",
            "-d",
            "postgres",
            "-X",
            "-tAc",
            f'ALTER DATABASE "{name}" IS_TEMPLATE false',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        [
            "psql",
            "-d",
            "postgres",
            "-X",
            "-tAc",
            f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS true',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["dropdb", "--if-exists", "--force", name], check=False, capture_output=True
    )


@pytest.fixture(scope="module")
def cluster(odoo_config):
    """Four databases covering every arm of the ``WHERE`` clause.

    ``foreign`` needs a second role, which needs CREATEROLE or superuser.
    Where that is not available the name is ``None`` and the one test that
    uses it skips — rather than skipping the whole class, which would lose
    the three filters that need no special privilege.
    """
    tag = uuid.uuid4().hex[:10]
    names = {
        "plain": f"odoo_list_plain_{tag}",
        "template": f"odoo_list_tmpl_{tag}",
        "noconn": f"odoo_list_noconn_{tag}",
        "foreign": f"odoo_list_other_{tag}",
    }
    role = f"odoo_list_role_{tag}"
    made, made_role = [], False
    try:
        for key in ("plain", "template", "noconn"):
            subprocess.run(
                ["createdb", "-T", "template0", names[key]],
                check=True,
                capture_output=True,
            )
            made.append(names[key])
        _psql(f'ALTER DATABASE "{names["template"]}" IS_TEMPLATE true')
        _psql(f'ALTER DATABASE "{names["noconn"]}" ALLOW_CONNECTIONS false')
        try:
            _psql(f'CREATE ROLE "{role}" LOGIN')
            made_role = True
            subprocess.run(
                ["createdb", "-T", "template0", "-O", role, names["foreign"]],
                check=True,
                capture_output=True,
            )
            made.append(names["foreign"])
        except subprocess.CalledProcessError:
            names["foreign"] = None
        yield names
    finally:
        for name in made:
            _drop(name)
        if made_role:
            subprocess.run(
                [
                    "psql",
                    "-d",
                    "postgres",
                    "-X",
                    "-tAc",
                    f'DROP ROLE IF EXISTS "{role}"',
                ],
                check=False,
                capture_output=True,
            )


@pytest.fixture
def listed(cluster):
    """``list_dbs(force=True)`` against a config that reaches the query.

    ``force`` bypasses the ``list_db`` gate — the point here is the SQL, and
    the gate is covered DB-free.  ``dbfilter``/``db_name`` must both be empty
    or the function returns before the query it exists to test; the
    session-scoped ``odoo_config`` parses an empty argv, so they are.
    """
    from odoo.service.db import list_dbs
    from odoo.tools import config

    assert not config["dbfilter"] and not config["db_name"], (
        "this test needs the SQL branch; a configured dbfilter or db_name "
        "returns before it"
    )
    return list_dbs(force=True)


@requires_pg
class TestListDbsVisibility:
    def test_a_database_this_role_owns_is_listed(self, cluster, listed):
        """Guard the guard: if nothing of ours is listed, every exclusion below
        would hold vacuously."""
        assert cluster["plain"] in listed, listed[:20]

    def test_a_template_is_not_listed(self, cluster, listed):
        """``datistemplate`` — offering one produces a database that cannot be
        served, and ``CREATE DATABASE ... TEMPLATE`` fails while anything is
        connected to it."""
        assert cluster["template"] not in listed

    def test_a_database_that_refuses_connections_is_not_listed(self, cluster, listed):
        assert cluster["noconn"] not in listed

    def test_a_database_owned_by_another_role_is_not_listed(self, cluster, listed):
        """The ownership filter, which is the tenant boundary on a shared cluster.

        Without it, an unauthenticated ``list`` enumerates every database on the
        host, whoever owns it.
        """
        if cluster["foreign"] is None:
            pytest.skip("no privilege to create a second role")
        assert cluster["foreign"] in _psql(
            "SELECT string_agg(datname, ',') FROM pg_database"
        ), "fixture did not create the foreign-owned database"
        assert cluster["foreign"] not in listed

    def test_the_maintenance_database_is_not_listed(self, listed):
        assert "postgres" not in listed

    def test_the_configured_template_is_not_listed(self, listed):
        """``db_template`` is excluded by name as well as by ``datistemplate``,
        because a deployment may point it at an ordinary database it clones."""
        from odoo.tools import config

        assert config["db_template"] not in listed

    def test_the_result_is_sorted(self, listed):
        """``ORDER BY datname``.  The database manager renders this list as-is,
        so an unordered result reshuffles the UI between scrapes."""
        assert listed == sorted(listed)
