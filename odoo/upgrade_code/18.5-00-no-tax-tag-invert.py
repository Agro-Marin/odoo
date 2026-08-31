import csv
import difflib
import logging
import re
import typing
from collections import defaultdict
from io import BytesIO, StringIO

from lxml import etree

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

    from odoo.cli.upgrade_code import FileAccessor, FileManager

_logger = logging.getLogger(__name__)

manual = {
    "base.ng": {"100": -1},
}


def template2country(template: str) -> str:
    return f"base.{template[:2]}"


def data_file_module_name(f: FileAccessor) -> str:
    return f.path.parts[f.path.parts.index("data") - 1]


def tax_grouper(row_iter: Iterator[dict[str, str]]) -> Iterator[list[dict[str, str]]]:
    current_batch = [next(row_iter)]
    for row in row_iter:
        if row["id"]:
            yield current_batch
            current_batch = [row]
        else:
            current_batch.append(row)
    yield current_batch


def remove_sign(
    tag_string: str,
    tag_signs: dict[str, int | str],
    type_tax_use: str,
    document_type: str,
) -> str:
    tags = []
    if not tag_string:
        return tag_string
    for tag in tag_string.split("||"):
        tag = tag.strip()
        if not tag.startswith(("-", "+")):
            tags.append(tag)
            continue
        sign_str, new_tag = tag[0], tag[1:]
        tags.append(new_tag)

        if type_tax_use not in ("sale", "purchase"):
            continue

        report_sign = 1 if sign_str == "+" else -1
        if (type_tax_use, document_type) in [
            ("sale", "invoice"),
            ("purchase", "refund"),
        ]:
            report_sign *= -1

        if existing_sign := tag_signs.get(new_tag):
            if existing_sign not in (report_sign, "error"):
                tag_signs[new_tag] = "error"
        else:
            tag_signs[new_tag] = report_sign

    return "||".join(tags)


def group_tax_use(csv_data: list[dict]) -> dict[str, str]:
    group_data: dict[str, str] = {}
    for row in csv_data:
        if row.get("amount_type") == "group":
            for xmlid in row["children_tax_ids"].split(","):
                assert (
                    xmlid not in group_data or group_data[xmlid] == row["type_tax_use"]
                )
                group_data[xmlid] = row["type_tax_use"]
    return group_data


def strip_signs_from_template(file, country_tax_signs: dict) -> None:
    csv_file = csv.DictReader(file.content.splitlines())
    csv_data = list(csv_file)
    if not csv_data:
        return
    if "repartition_line_ids/document_type" not in csv_data[0]:
        return

    group_data = group_tax_use(csv_data)

    buffer = StringIO()
    writer = csv.DictWriter(
        buffer,
        # fieldnames is None until a header is read; csv_data being non-empty
        # means it has been.
        fieldnames=csv_file.fieldnames or (),
        delimiter=",",
        quotechar='"',
        quoting=csv.QUOTE_ALL,
        lineterminator="\n",
    )
    writer.writeheader()
    for tax_rows in tax_grouper(iter(csv_data)):
        type_tax_use = tax_rows[0]["type_tax_use"]
        if type_tax_use == "none":
            type_tax_use = group_data.get(tax_rows[0]["id"]) or "none"
        assert type_tax_use
        for row in tax_rows:
            document_type = row["repartition_line_ids/document_type"]
            writer.writerow(
                {
                    fname: (
                        remove_sign(
                            value, country_tax_signs, type_tax_use, document_type
                        )
                        if fname == "repartition_line_ids/tag_ids"
                        else value
                    )
                    for fname, value in row.items()
                }
            )
    file.content = buffer.getvalue()


def report_sign_conflicts(tag_signs: dict) -> dict[str, list[str]]:
    return {
        country: errors
        for country, country_tax_signs in tag_signs.items()
        if (
            errors := [
                tag for tag, sign in country_tax_signs.items() if sign == "error"
            ]
        )
    }


def invert_report_expressions(tree, tag_signs: dict, unknowns: dict) -> int:
    inverted = 0
    for report_node in tree.xpath("//record[@model='account.report']"):
        country_node = report_node.find("field[@name='country_id']")
        if country_node is None:
            continue
        country_code = country_node.attrib["ref"]
        country_tax_signs = tag_signs[country_code]
        for expression_node in report_node.findall(
            ".//record[@model='account.report.expression']"
        ):
            engine_node = expression_node.find("field[@name='engine']")
            if engine_node.text != "tax_tags":
                continue
            formula_node = expression_node.find("field[@name='formula']")
            tag = formula_node.text
            if manual_sign := manual.get(country_code, {}).get(tag):
                if manual_sign == -1:
                    inverted += 1
                    formula_node.text = "-" + formula_node.text
            elif tag not in country_tax_signs:
                unknowns[country_code].append(tag)
            elif country_tax_signs[tag] == -1:
                inverted += 1
                formula_node.text = "-" + formula_node.text
    return inverted


def formula_only_diff(before: str, tree) -> str:
    return "".join(
        diff[2:]
        for diff in difflib.ndiff(
            before.splitlines(keepends=True),
            etree.tostring(tree, encoding="utf-8").decode().splitlines(keepends=True),
        )
        if (
            diff.startswith((" ", "-"))
            or re.match(r"""\+\s*<field name=["']formula["']""", diff)
        )
        and not re.match(r"""-\s*<field name=["']formula["']""", diff)
    )


def upgrade(file_manager: FileManager) -> None:
    tax_template_files = [
        f
        for f in file_manager
        if f.path.suffix == ".csv"
        and f.path.parts[-2] == "template"
        and f.path.stem.startswith("account.tax-")
    ]
    nb_template_files = len(tax_template_files)
    tax_report_files = [
        f
        for f in file_manager
        if f.path.suffix == ".xml"
        and "data" in f.path.parts
        and data_file_module_name(f).startswith("l10n_")
    ]
    nb_report_files = len(tax_report_files)

    tag_signs: dict = defaultdict(dict)
    for i, file in enumerate(tax_template_files):
        file_manager.print_progress(i, nb_template_files + nb_report_files, file.path)
        country = template2country(file.path.stem.split("-", maxsplit=1)[1])
        strip_signs_from_template(file, tag_signs[country])

    if conflicts := report_sign_conflicts(tag_signs):
        _logger.warning("\n\n\nInconsistent tag signs found:")
        for country in sorted(conflicts):
            _logger.warning("%s: %s", country, conflicts[country])

    unknowns: dict = defaultdict(list)
    for i, file in enumerate(tax_report_files):
        file_manager.print_progress(
            nb_template_files + i,
            nb_template_files + nb_report_files,
            file.path,
        )
        tree = etree.parse(BytesIO(file.content.encode()))
        if invert_report_expressions(tree, tag_signs, unknowns):
            file.content = formula_only_diff(file.content, tree)

    if unknowns:
        _logger.warning("\n\n\nUnknown tag signs found:")
        for country in sorted(unknowns):
            _logger.warning("%s: %s", country, unknowns[country])
