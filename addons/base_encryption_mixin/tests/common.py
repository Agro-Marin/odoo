"""A working Fernet key for any suite that touches encrypted material.

Every model built on ``encryption.mixin`` refuses to store anything without
``ODOO_API_ENCRYPTION_KEY`` in the process environment -- deliberately, because the
key must not live in the database. The consequence for tests is that a suite which
does not provide one does not skip: it fails, once per test that stores a secret,
with ``ValidationError: Encryption key not configured!``.

Measured on this workspace, that is 61 failures across ``credential`` and
``api_transport`` on a run where the variable happened to be unset -- and no CI lane
runs either suite, so nobody sees them go green anywhere else. Sixty-one red tests
in the two modules a change was just made to is exactly the shape of an
unattributable failure, and it costs a diagnostic detour every time.

Seventeen test files already carry their own copy of the same eight lines. This is
where the copy belongs: the module that owns the variable is the one that should
say how a test gets one.

Usage::

    class TestSomething(EncryptionKeyCase, TransactionCase):
        pass

An environment that already has a key keeps it, so a developer running against a
real key still tests against that key.
"""

import os
from unittest.mock import patch

from cryptography.fernet import Fernet


class EncryptionKeyCase:
    """Mixin that guarantees a usable ``ODOO_API_ENCRYPTION_KEY`` for the class.

    Mix it in *before* the test case, so its ``setUpClass`` runs first and the key
    is in place before any fixture stores a secret.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not os.environ.get("ODOO_API_ENCRYPTION_KEY"):
            cls.enterClassContext(
                patch.dict(
                    os.environ,
                    {"ODOO_API_ENCRYPTION_KEY": Fernet.generate_key().decode()},
                )
            )
            # The key version is cached per process, so a suite that installs a key
            # after something already looked would otherwise keep the old answer.
            cls.env["encryption.mixin"]._invalidate_key_version_cache()
            cls.addClassCleanup(
                cls.env["encryption.mixin"]._invalidate_key_version_cache
            )
