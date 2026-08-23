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
        # NO `file.content = content`, on purpose, and it is not an oversight to
        # correct — that was tried on 2026-08-23 and reverted the same hour. Two
        # tests in `base/tests/test_cli.py` pin this script as inert
        # (`test_upgrade_code_example` asserts a `--dry-run` prints nothing,
        # `test_upgrade_code_standalone_runs` asserts it exits 0, which
        # `--dry-run` only does when no file is dirty), because it is the
        # fixture the CLI's own tests run against. Its substitutions are a
        # demonstration of the API — they swap quote styles and would fight
        # `ruff format` — so a version range that swept it up would mangle every
        # `models/*.py` in the checkout for nothing. What a real script does
        # with `content` is assign it back; see any other file here.

        file_manager.print_progress(fileno, len(files))
