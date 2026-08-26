import subprocess
import uuid

import pytest

from .._pg import pg_reachable
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
    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
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
        assert cluster["plain"] in listed, listed[:20]

    def test_a_template_is_not_listed(self, cluster, listed):
        assert cluster["template"] not in listed

    def test_a_database_that_refuses_connections_is_not_listed(self, cluster, listed):
        assert cluster["noconn"] not in listed

    def test_a_database_owned_by_another_role_is_not_listed(self, cluster, listed):
        if cluster["foreign"] is None:
            pytest.skip("no privilege to create a second role")
        assert cluster["foreign"] in _psql(
            "SELECT string_agg(datname, ',') FROM pg_database"
        ), "fixture did not create the foreign-owned database"
        assert cluster["foreign"] not in listed

    def test_the_maintenance_database_is_not_listed(self, listed):
        assert "postgres" not in listed

    def test_the_configured_template_is_not_listed(self, listed):
        from odoo.tools import config

        assert config["db_template"] not in listed

    def test_the_result_is_sorted(self, listed):
        assert listed == sorted(listed)
