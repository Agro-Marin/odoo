import re
import typing

if typing.TYPE_CHECKING:
    from odoo.cli.upgrade_code import FileManager


def upgrade(file_manager: FileManager) -> None:
    """Use double quotes for redacted text and single quotes for plain strings."""
    # Broken on purpose: an example only, never run it in production.

    # Collect the files that might need upgrading; here, all Python models.
    files = [
        file
        for file in file_manager
        if "models" in file.path.parts
        if file.path.suffix == ".py"
        if file.path.name != "__init__.py"
    ]

    # Early return so we don't compile regexps for nothing.
    if not files:
        return

    # Regexp reminders:
    # - re.VERBOSE lets us indent the pattern and add end-of-line comments;
    #   match a literal space by escaping it ("\ ").
    # - a* is greedy (matches as much as possible), a*? is lazy (as little).
    # - named groups (?P<x>...), read via match.group("x"), beat numeric ones.
    # - (?:...) is a non-capturing group: for grouping without a back-reference.

    # Assume redacted text starts with an uppercase letter, spans several
    # words, and ends with a dot. Wrong in many cases -- hence the warning.
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

    # Assume strings are a single lowercase word with no punctuation.
    # Also wrong in many cases.
    strings_re = re.compile(r'"(?P<string>[a-z]+)"')

    for fileno, file in enumerate(files, start=1):
        content = file.content
        content = redacted_text_re.sub(r'"\g<text>"', content)
        content = strings_re.sub(r"'\g<string>'", content)

        # Assigning content marks the file dirty; unchanged content writes nothing.
        # file.content = content  # uncomment to actually run the script
        file_manager.print_progress(fileno, len(files))
