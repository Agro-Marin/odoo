import functools
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from . import _pretty_xml, _sort_xml_records, _xml_identity
from .lint_case import core_data_files


@dataclass(frozen=True, slots=True)
class Sweep:
    changed: list[str] = field(default_factory=list)
    declined: list[str] = field(default_factory=list)
    unsettled: list[str] = field(default_factory=list)
    unparseable: list[str] = field(default_factory=list)
    checked: int = 0


def _sweep(fixer) -> Sweep:
    changed: list[str] = []
    declined: list[str] = []
    unsettled: list[str] = []
    unparseable: list[str] = []
    checked = 0

    with tempfile.TemporaryDirectory() as tmp:
        for index, source in enumerate(core_data_files()):
            original = source.read_bytes()
            try:
                _xml_identity.comparable(original)
            except etree.LxmlError as exc:
                unparseable.append(f"{source}: {exc}")
                continue
            checked += 1

            target = Path(tmp) / f"{index}.xml"
            target.write_bytes(original)
            first = fixer(target)
            if first is None:
                declined.append(str(source))
                continue
            if first:
                changed.append(str(source))
                once = target.read_bytes()
                if fixer(target) and target.read_bytes() != once:
                    unsettled.append(str(source))

    return Sweep(changed, declined, unsettled, unparseable, checked)


@functools.cache
def formatter_sweep() -> Sweep:
    return _sweep(_pretty_xml.format_xml_file)


@functools.cache
def sorter_sweep() -> Sweep:
    return _sweep(_sort_xml_records.sort_xml_file)
