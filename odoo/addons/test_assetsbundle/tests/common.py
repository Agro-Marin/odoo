import os
import pathlib
import time
from unittest.mock import patch

import odoo.modules
from odoo.tests.common import TransactionCase

ORIGINAL_PATH_STAT = pathlib.Path.stat


def asset_file(url, content, last_modified=1.0):
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


def make_cursor_readonly(case):
    cr = case.env.cr
    original = cr._readonly
    cr._readonly = True
    case.addCleanup(setattr, cr, "_readonly", original)


class Manifests(dict):
    def __init__(self, default):
        self.defaults = default

    def __missing__(self, key):
        return self.defaults(key)


class AddonManifestPatched(TransactionCase):
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

    def _bump_last_attachment_write_date(self, offset_seconds):
        """Push the most recently created ir.attachment's write_date
        `offset_seconds` into the future.

        write_date is a magic column the ORM's write() silently ignores,
        so there is no way to fake it through the ORM the way _touch()
        fakes a source file's mtime — this goes through raw SQL
        (PostgreSQL-only, via clock_timestamp()) on purpose, to simulate
        a stale server clock relative to a bundle's source files.
        """
        self.env["ir.attachment"].flush_model(["checksum", "write_date"])
        self.cr.execute(
            "UPDATE ir_attachment SET write_date = clock_timestamp() + (%s * interval '1 second') "
            "WHERE id = (SELECT max(id) FROM ir_attachment)",
            (offset_seconds,),
        )
        self.env["ir.attachment"].invalidate_model(["write_date"])
