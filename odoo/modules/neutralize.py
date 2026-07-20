import logging
import typing
from contextlib import suppress

from odoo.modules.module import Manifest
from odoo.tools.misc import file_open

if typing.TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from odoo.db import Cursor

_logger = logging.getLogger(__name__)


def get_installed_modules(cursor: Cursor) -> list[str]:
    cursor.execute("""
        SELECT name
          FROM ir_module_module
         WHERE state IN ('installed', 'to upgrade', 'to remove');
    """)
    return [result[0] for result in cursor.fetchall()]


def get_neutralization_queries(modules: Iterable[str]) -> Iterator[str]:
    for module in modules:
        # An installed module missing from the addons path (e.g. neutralize run
        # without the enterprise dir) would have its neutralize.sql silently
        # skipped below; warn so the operator knows neutralization is incomplete.
        if Manifest.for_addon(module, display_warning=False) is None:
            _logger.warning(
                "Module %r is installed but not found on the addons path; its "
                "neutralization (if any) is SKIPPED. The database may not be "
                "fully neutralized — configure all addons paths and re-run.",
                module,
            )
            continue
        filename = f"{module}/data/neutralize.sql"
        with suppress(FileNotFoundError):
            with file_open(filename) as file:
                yield file.read().strip()


def neutralize_database(cursor: Cursor) -> None:
    installed_modules = get_installed_modules(cursor)
    queries = get_neutralization_queries(installed_modules)
    for query in queries:
        cursor.execute(query)
    _logger.info("Neutralization finished")
