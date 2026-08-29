import csv


def patch_module() -> None:
    csv.field_size_limit(500 * 1024 * 1024)
