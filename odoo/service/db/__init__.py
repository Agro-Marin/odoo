"""Database management: the ``/web/database/manager`` service.

``service/db.py`` was one flat module of 1633 lines and 42 top-level
definitions — the largest un-decomposed module in the core, and the least
cohesive of its large ones. ``tools/config.py`` is bigger and
``orm/fields/base.py`` comparable, but both are *cohesive*: few top-level names,
deep bodies. This one was large **and** flat, which is the combination that
resists reading, and it held four unrelated concerns at once (ADR-0014).

The split is ADR-0003's, applied one package over: that record packagised
``sql_db.py`` into ``odoo/db/`` on the same argument, and the tiering it
produced became enforceable contracts.

```
rpc          the dispatch table and its master-password gate
 ├── restore   restoring a backup, and the archive-bomb bounds
 │    ├── lifecycle
 │    └── listing
 ├── dump      pg_dump, the zip envelope, the filestore beside it
 │    └── listing
 ├── lifecycle create / drop / duplicate / rename, and the DDL retries
 │    └── listing
 └── listing   which databases exist, which are exposed, static lists
```

Dependencies point one way, so the modules can be read in that order. The
log channel is unchanged: every module logs to ``odoo.service.db``, as
``_db_helpers`` and ``_dump_scanner`` already did literally.

**Names re-exported here are the public surface, and patching them is not the
same as patching their definition.** ``mock.patch("odoo.service.db.X")`` rebinds
the alias in this module; a caller inside ``lifecycle`` that reached ``X``
directly will not see it. Tests must patch the owning module —
``odoo.service.db.lifecycle.X``. ``tests/service/test_db_patch_targets.py``
fails on a target the named module does not actually use, because the failure
mode otherwise is a patch that silently does nothing and a test that passes
while asserting against the real implementation.
"""

from .._db_helpers import (
    DBNAME_MAX_LENGTH,
    DBNAME_PATTERN,
    DatabaseExists,
    check_db_management_enabled,
    check_super,
    database_identifier,
    validate_db_name,
)
from odoo.db import SYSTEM_DBS
from .dump import BACKUP_FORMATS, dump_db, dump_db_manifest, exp_dump
from .lifecycle import (
    _create_empty_database,
    _drop_database,
    _duplicate_database,
    _rename_database,
    exp_create_database,
    exp_drop,
    exp_duplicate_database,
    exp_rename,
)
from .listing import (
    check_db_exposed,
    exp_db_exist,
    exp_list,
    exp_list_countries,
    exp_list_lang,
    exp_server_version,
    list_db_incompatible,
    list_dbs,
)
from .restore import exp_restore, restore_db
from .rpc import dispatch, exp_change_admin_password, exp_migrate_databases

__all__ = (
    "BACKUP_FORMATS",
    "DBNAME_MAX_LENGTH",
    "DBNAME_PATTERN",
    "SYSTEM_DBS",
    "DatabaseExists",
    "_create_empty_database",
    "_drop_database",
    "_duplicate_database",
    "_rename_database",
    "check_db_exposed",
    "check_db_management_enabled",
    "check_super",
    "database_identifier",
    "dispatch",
    "dump_db",
    "dump_db_manifest",
    "exp_change_admin_password",
    "exp_create_database",
    "exp_db_exist",
    "exp_drop",
    "exp_dump",
    "exp_duplicate_database",
    "exp_list",
    "exp_list_countries",
    "exp_list_lang",
    "exp_migrate_databases",
    "exp_rename",
    "exp_restore",
    "exp_server_version",
    "list_db_incompatible",
    "list_dbs",
    "restore_db",
    "validate_db_name",
)
