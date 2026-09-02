import threading
from pathlib import Path

import pytest

from odoo.tools.files import (
    file_open,
    file_open_temporary_directory,
    file_open_temporary_paths,
    file_path,
)


def test_the_allowlist_is_empty_outside_a_block():
    assert file_open_temporary_paths() == ()


def test_the_block_scopes_the_allowlist_and_needs_no_environment():
    with file_open_temporary_directory() as tmp_dir:
        assert file_open_temporary_paths() == (tmp_dir,)
        Path(tmp_dir, "probe.txt").write_text("inside", encoding="utf-8")
        assert file_path(f"{tmp_dir}/probe.txt") == f"{tmp_dir}/probe.txt"
        with file_open(f"{tmp_dir}/probe.txt") as fh:
            assert fh.read() == "inside"
    assert file_open_temporary_paths() == ()
    with pytest.raises(FileNotFoundError):
        file_path(f"{tmp_dir}/probe.txt")


def test_nested_blocks_stack_and_unwind_in_order():
    with file_open_temporary_directory() as outer:
        with file_open_temporary_directory() as inner:
            assert file_open_temporary_paths() == (outer, inner)
        assert file_open_temporary_paths() == (outer,)
    assert file_open_temporary_paths() == ()


def test_an_exception_inside_the_block_still_unwinds():
    with pytest.raises(RuntimeError), file_open_temporary_directory():
        assert len(file_open_temporary_paths()) == 1
        raise RuntimeError("boom")
    assert file_open_temporary_paths() == ()


def test_the_allowlist_does_not_leak_into_another_thread():
    seen = []
    with file_open_temporary_directory():
        worker = threading.Thread(
            target=lambda: seen.append(file_open_temporary_paths())
        )
        worker.start()
        worker.join()
    assert seen == [()], "the sandbox allowlist is scoped to the opening thread"


def test_a_legacy_env_argument_is_accepted_and_ignored():
    with file_open_temporary_directory(object()) as tmp_dir:
        assert file_open_temporary_paths() == (tmp_dir,)
