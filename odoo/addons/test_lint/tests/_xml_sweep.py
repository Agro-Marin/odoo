"""One pass of a fixer over every core data file, shared by the gates that ask.

`PrettyXmlLinter.test_xml_formatting` dry-ran the formatter over all 3939 data
files and `TestFixersOverTheRepository.test_the_formatter_preserves_every_data_file`
ran it for real over byte-identical copies. Measured side by side the two produce
the *identical* 3641-file set -- 8.2s CPU each, and one of them was re-deriving
what the other already knew.

They read this instead. The pass runs on copies in a scratch directory, so it
answers the dry-run question and the round-trip question at once without
touching the tree.
"""

import functools
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from . import _pretty_xml, _sort_xml_records, _xml_identity
from .lint_case import core_data_files


@dataclass(frozen=True, slots=True)
class Sweep:
    #: Files the fixer would rewrite -- the gate's debt.
    changed: list[str] = field(default_factory=list)
    #: Files it refused, because the rewrite would not say the same thing. Safe,
    #: but the gate can never report on them, so the set is pinned.
    declined: list[str] = field(default_factory=list)
    #: Files that change *again* on a second pass, so the gate could never go
    #: green on them however often you ran the fixer.
    unsettled: list[str] = field(default_factory=list)
    #: Files that are not XML at all. They used to be dropped in silence by every
    #: XML gate at once.
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
