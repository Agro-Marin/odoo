import csv


def patch_module() -> None:

    class UNIX_LINE_TERMINATOR(csv.excel):
        lineterminator = "\n"

    csv.field_size_limit(500 * 1024 * 1024)
    csv.register_dialect("UNIX", UNIX_LINE_TERMINATOR)
