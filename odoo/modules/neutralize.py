import logging
import typing
from contextlib import suppress

from odoo.modules._protocols import SqlReader
from odoo.modules.module import Manifest
from odoo.tools.misc import file_open

if typing.TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


_logger = logging.getLogger(__name__)


def get_installed_module_names(cursor: SqlReader) -> list[str]:
    cursor.execute("""
        SELECT name
          FROM ir_module_module
         WHERE state IN ('installed', 'to upgrade', 'to remove');
    """)
    return [result[0] for result in cursor.fetchall()]


def iter_neutralization_queries(modules: Iterable[str]) -> Iterator[tuple[str, str]]:
    for module in modules:
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
                if content := file.read().strip():
                    yield module, content


def get_neutralization_queries(modules: Iterable[str]) -> Iterator[str]:
    for _module, query in iter_neutralization_queries(modules):
        yield query


def neutralize_database(cursor: SqlReader) -> None:
    for module, query in iter_neutralization_queries(
        get_installed_module_names(cursor)
    ):
        try:
            cursor.execute(query)
        except Exception as exc:
            exc.add_note(f"while neutralizing {module} ({module}/data/neutralize.sql)")
            raise
    _logger.info("Neutralization finished")
