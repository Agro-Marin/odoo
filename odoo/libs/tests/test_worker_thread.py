import threading

import pytest

from odoo.libs.worker_thread import working_on_database


@pytest.fixture(autouse=True)
def _no_marker():
    thread = threading.current_thread()
    had = hasattr(thread, "dbname")
    previous = getattr(thread, "dbname", None)
    if had:
        del thread.dbname
    yield
    if had:
        thread.dbname = previous
    elif hasattr(thread, "dbname"):
        del thread.dbname


def test_the_marker_is_set_inside_and_gone_after():
    thread = threading.current_thread()
    with working_on_database("db_a"):
        assert thread.dbname == "db_a"
    assert not hasattr(thread, "dbname"), (
        "a worker that polls several databases in turn must leave the thread as "
        "it found it; absent is not the same as None, and the log formatter "
        "reads the attribute"
    )


def test_a_previous_marker_is_restored_not_cleared():
    thread = threading.current_thread()
    thread.dbname = "outer"
    with working_on_database("inner"):
        assert thread.dbname == "inner"
    assert thread.dbname == "outer"


def test_nesting_unwinds_in_order():
    thread = threading.current_thread()
    with working_on_database("one"):
        with working_on_database("two"):
            assert thread.dbname == "two"
        assert thread.dbname == "one"
    assert not hasattr(thread, "dbname")


def test_the_marker_survives_long_enough_for_the_handler_to_log():
    thread = threading.current_thread()
    seen = []
    with pytest.raises(ValueError):
        with working_on_database("db_b"):
            try:
                raise ValueError("boom")
            except ValueError:
                seen.append(thread.dbname)
                raise
    assert seen == ["db_b"], (
        "every except branch in _process_jobs names the database in its message; "
        "the log prefix has to agree with it"
    )
    assert not hasattr(thread, "dbname")


def test_an_escaping_exception_still_restores():
    thread = threading.current_thread()
    thread.dbname = "outer"
    with pytest.raises(RuntimeError):
        with working_on_database("inner"):
            raise RuntimeError("boom")
    assert thread.dbname == "outer"
