import atexit
import logging
import os
from pathlib import Path

import pytest

from odoo.service import _base_server

_logger = logging.getLogger(__name__)


@pytest.fixture
def isolated_hooks(monkeypatch):
    monkeypatch.setattr(_base_server, "_process_exit_hooks", [])
    registered = []
    monkeypatch.setattr(atexit, "register", registered.append)
    return registered


def _touch(path: Path):
    def hook():
        path.write_text("ran", encoding="utf-8")

    return hook


def test_a_hook_is_registered_once_and_with_atexit(isolated_hooks, tmp_path):
    hook = _touch(tmp_path / "marker")
    _base_server.register_process_exit_hook(hook)
    _base_server.register_process_exit_hook(hook)
    assert _base_server._process_exit_hooks == [(os.getpid(), hook)]
    assert isolated_hooks.count(hook) == 1


def test_a_process_runs_its_own_hooks_and_none_its_parent_registered(
    isolated_hooks, monkeypatch, tmp_path
):
    parents = tmp_path / "parent"
    childs = tmp_path / "child"
    _base_server.register_process_exit_hook(_touch(parents))
    # a prefork child: a new pid that inherited the parent's list
    monkeypatch.setattr(os, "getpid", lambda: -1)
    _base_server.register_process_exit_hook(_touch(childs))
    _base_server.run_process_exit_hooks(_logger)
    assert childs.exists()
    assert not parents.exists()


def test_a_failing_hook_does_not_stop_the_others(isolated_hooks, tmp_path):
    marker = tmp_path / "marker"

    def failing():
        raise RuntimeError("boom")

    _base_server.register_process_exit_hook(failing)
    _base_server.register_process_exit_hook(_touch(marker))
    _base_server.run_process_exit_hooks(_logger)
    assert marker.exists()
