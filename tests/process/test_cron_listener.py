"""The cron listener protocol, pinned against a real server and a real PostgreSQL.

The unit suites mock this path end to end, and the one regression that mattered
(75de99404cc) sailed through them; what a refactor of the listeners must not
break is observable only here: a booted server LISTENs, a NOTIFY wakes it, a
killed backend is reconnected and the re-armed listener still hears the next
NOTIFY. Both loops — the threaded cron thread and the prefork WorkerCron — are
pinned, because they are two implementations of one protocol.
"""

import os
import time

import psutil
import pytest

from .conftest import REPO_ROOT, requires_pg, requires_posix

CRON_CHANNEL = "cron_trigger"

WAKE_TIMEOUT_S = 15.0

RECONNECT_TIMEOUT_S = 20.0


def test_the_channel_literal_matches_the_source():
    text = (REPO_ROOT / "odoo" / "tools" / "constants.py").read_text()
    assert f'CRON_TRIGGER_CHANNEL = "{CRON_CHANNEL}"' in text, (
        "the channel name moved in odoo/tools/constants.py; every NOTIFY this "
        "file sends now targets a channel nothing listens on"
    )


def _connect_postgres():
    import psycopg

    return psycopg.connect(dbname="postgres", autocommit=True)


@pytest.fixture
def cron_db():
    name = f"proccron_{os.getpid()}"
    with _connect_postgres() as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.execute(f'CREATE DATABASE "{name}"')
    yield name
    with _connect_postgres() as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid != pg_backend_pid()",
            (name,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


def _app_label() -> str:
    return f"proccron{os.getpid()}"


def _listener_pids(label: str) -> set[int]:
    # After arming, the backend sits idle with query=COMMIT, so LISTEN is not
    # visible in pg_stat_activity; the NOTIFY-wake assertion is what proves the
    # subscription. The maintenance-DB connection carrying our label is the
    # listener (pooled ones are transient, and all belong to this server).
    with _connect_postgres() as conn:
        rows = conn.execute(
            "SELECT pid FROM pg_stat_activity "
            "WHERE application_name LIKE %s AND datname = 'postgres' "
            "AND pid != pg_backend_pid()",
            (label + "%",),
        ).fetchall()
    return {pid for (pid,) in rows}


def _notify(db_name: str) -> None:
    with _connect_postgres() as conn:
        conn.execute("SELECT pg_notify(%s, %s)", (CRON_CHANNEL, db_name))


def _wait_for(predicate, timeout: float, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


def _mentions(handle, db_name: str) -> int:
    return handle.log_text().count(db_name)


def _settled_mentions(handle, db_name: str) -> int:
    # The first pass sweeps every known database immediately, so the name may
    # already be in the log; wait for that burst to stop moving.
    count = _mentions(handle, db_name)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        time.sleep(1.0)
        now = _mentions(handle, db_name)
        if now == count:
            return now
        count = now
    return count


def _assert_notify_wakes_and_reconnect_rearms(srv, db_name: str, label: str) -> None:
    listeners = _wait_for(lambda: _listener_pids(label), timeout=30)
    assert listeners, (
        f"no LISTEN backend with application_name {label}* appeared; the cron "
        f"listener never armed. Log tail:\n"
        + "\n".join(srv.log_text().splitlines()[-10:])
    )

    baseline = _settled_mentions(srv, db_name)
    _notify(db_name)
    woke = _wait_for(lambda: _mentions(srv, db_name) > baseline, timeout=WAKE_TIMEOUT_S)
    assert woke, (
        f"NOTIFY {CRON_CHANNEL},{db_name} produced no reaction within "
        f"{WAKE_TIMEOUT_S:.0f}s — the listener is not draining its channel"
    )

    with _connect_postgres() as conn:
        for pid in listeners:
            conn.execute("SELECT pg_terminate_backend(%s)", (pid,))
    rearmed = _wait_for(
        lambda: _listener_pids(label) - listeners, timeout=RECONNECT_TIMEOUT_S
    )
    assert rearmed, (
        f"no new LISTEN backend within {RECONNECT_TIMEOUT_S:.0f}s of killing "
        f"{sorted(listeners)}; the reconnect path is dead. Log tail:\n"
        + "\n".join(srv.log_text().splitlines()[-10:])
    )
    assert "reconnect" in srv.log_text().lower()

    baseline = _settled_mentions(srv, db_name)
    _notify(db_name)
    woke_again = _wait_for(
        lambda: _mentions(srv, db_name) > baseline, timeout=WAKE_TIMEOUT_S
    )
    assert woke_again, (
        "the re-armed listener does not hear NOTIFY — the reconnect re-opened "
        "a connection but never re-issued LISTEN"
    )


def _cron_args(db_name: str, label: str) -> list[str]:
    return [
        "--max-cron-threads",
        "1",
        "--db-filter",
        f"^{db_name}$",
        "--db_app_name",
        label + "{pid}",
    ]


@requires_pg
@requires_posix
def test_threaded_cron_listener_wakes_and_survives_a_killed_backend(server, cron_db):
    label = _app_label()
    srv = server("--workers", "0", *_cron_args(cron_db, label))
    _assert_notify_wakes_and_reconnect_rearms(srv, cron_db, label)


@requires_pg
@requires_posix
def test_prefork_cron_worker_wakes_and_survives_a_killed_backend(server, cron_db):
    label = _app_label()
    srv = server("--workers", "1", *_cron_args(cron_db, label))
    assert srv.wait_until(
        lambda: any(
            p.is_running() and p.status() != psutil.STATUS_ZOMBIE
            for p in srv.children()
        ),
        timeout=30,
    ), "prefork master forked no children"
    _assert_notify_wakes_and_reconnect_rearms(srv, cron_db, label)
