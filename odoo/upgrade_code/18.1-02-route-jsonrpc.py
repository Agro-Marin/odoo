import typing

if typing.TYPE_CHECKING:
    from odoo.cli.upgrade_code import FileManager


def upgrade(file_manager: FileManager) -> None:
    files = [
        f
        for f in file_manager
        if "controllers" in f.path.parts
        if f.path.suffix == ".py"
    ]

    # `start=1`, like every other script: from 0 the bar opened at 0% on the
    # first file and never reached 100%.
    for fileno, file in enumerate(files, start=1):
        file.content = file.content.replace('type="json",', 'type="jsonrpc",').replace(
            "type='json',", "type='jsonrpc',"
        )
        file_manager.print_progress(fileno, len(files))
