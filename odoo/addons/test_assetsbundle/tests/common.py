"""Fixtures shared by the asset-pipeline suites.

Every helper here arrived as a duplicate. ``asset_file`` had six byte-identical
copies and ``make_cursor_readonly`` two, which is the failure mode a pipeline
suite can least afford: a bundle's behaviour turns on the exact shape of its
input, so six independently-editable definitions of "a file spec" are six
chances for two suites to be silently testing different things.

Nothing in here is collected as a test -- ``tests/__init__.py`` does not import
it, and the base classes below carry no ``test_`` methods.
"""

import os
import pathlib
import time
from unittest.mock import patch

import odoo.modules
from odoo.tests.common import TransactionCase

ORIGINAL_PATH_STAT = pathlib.Path.stat


def asset_file(url, content, last_modified=1.0):
    """One entry of the ``files`` list ``AssetsBundle`` is constructed from.

    ``filename`` is None on purpose: these specs carry their content inline, so
    the bundle never goes to disk and the test stays hermetic.
    """
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


def make_cursor_readonly(case):
    """Flip *case*'s cursor to readonly, restoring it on cleanup.

    Reaches for the private ``_readonly`` because that is the only way to make
    a test transaction claim to be a replica cursor without actually opening
    one; the paths under test branch on ``cr.readonly``.
    """
    cr = case.env.cr
    original = cr._readonly
    cr._readonly = True
    case.addCleanup(setattr, cr, "_readonly", original)


class Manifests(dict):
    """Manifest lookup that falls back to the real one for unknown addons.

    Lets a test declare a fake addon (``self.manifests["test_other"] = {...}``)
    while every other module still resolves normally.
    """

    def __init__(self, default):
        self.defaults = default

    def __missing__(self, key):
        return self.defaults(key)


class AddonManifestPatched(TransactionCase):
    """Pins the installed-addon set and the manifest source for the test.

    Asset resolution reads both, so without this the expected bundle contents
    would depend on which modules the database happens to carry.
    """

    def setUp(self):
        super().setUp()

        self.installed_modules = {"base", "test_assetsbundle"}
        self.manifests = Manifests(odoo.modules.Manifest.for_addon)

        self.patch(self.env.registry, "_init_modules", self.installed_modules)
        self.patch(
            odoo.modules.Manifest,
            "for_addon",
            lambda module, **kw: self.manifests[module],
        )


class FileTouchable(AddonManifestPatched):
    """Lets a test pretend a source file was modified, without writing to it.

    Bundle versions key on mtime, so invalidation tests need a file to look
    newer. Touching it for real would dirty the checkout, so ``Path.stat`` is
    patched to report a different ``st_mtime`` for the chosen paths only.
    """

    def setUp(self):
        super().setUp()
        self.touches = {}

    def _touch(self, filepath, touch_time=None):
        self.touches[filepath] = touch_time or time.time()

        def patched_stat(path_self, *args, **kwargs):
            result = ORIGINAL_PATH_STAT(path_self, *args, **kwargs)
            touched = self.touches.get(str(path_self))
            if touched is not None:
                return os.stat_result(
                    (
                        result.st_mode,
                        result.st_ino,
                        result.st_dev,
                        result.st_nlink,
                        result.st_uid,
                        result.st_gid,
                        result.st_size,
                        result.st_atime,
                        touched,
                        result.st_ctime,
                    )
                )
            return result

        return patch.object(pathlib.Path, "stat", patched_stat)
