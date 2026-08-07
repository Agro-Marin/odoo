import re
import typing

if typing.TYPE_CHECKING:
    from odoo.cli.upgrade_code import FileManager


def upgrade(file_manager: FileManager) -> None:

    files = [
        file
        for file in file_manager
        if "models" in file.path.parts
        if file.path.suffix == ".py"
        if file.path.name != "__init__.py"
    ]

    if not files:
        return

    redacted_text_re = re.compile(
        r"""
        '           # Opening single quote
        (?P<text>
            [A-Z][^'\s]*?\   # First word
            (?:[^'\s]*?\ )*  # All middle words
            [^'\s]*?\.       # Final word
        )
        '           # Closing single quote
    """,
        re.VERBOSE,
    )

    strings_re = re.compile(r'"(?P<string>[a-z]+)"')

    for fileno, file in enumerate(files, start=1):
        content = file.content
        content = redacted_text_re.sub(r'"\g<text>"', content)
        content = strings_re.sub(r"'\g<string>'", content)

        file_manager.print_progress(fileno, len(files))
