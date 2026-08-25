"""Every section banner must name the code that follows it.

The big files in this suite navigate by

    # ---------------------------------------------------------------------
    # Subject
    # ---------------------------------------------------------------------

    class TestSubject:

and those banners are the only index a reader gets — ``test_server.py`` alone
carries thirty-odd across 3 800 lines.  They drift silently: a class moved to a
sibling file takes its tests with it and leaves its banner behind, where it then
labels whatever happened to follow.  Fourteen were wrong when this gate was
written, all of them from the split that moved ``_watcher``, ``_cron`` and
``lifecycle`` coverage out of ``test_server.py``:

* nine ORPHANED — the banner's subject was no longer in the file at all
  (``# FSWatcherBase.handle_file()`` and ``# FSWatcherInotify: ...`` were the
  only two mentions of the watcher left in ``test_server.py``, and both were
  banners);
* two MISPLACED — the subject was still there, further down, with other classes
  wedged in between;
* three DANGLING — a banner at end of file with nothing after it at all.

Checking this by matching a banner's words against the following class name was
tried and rejected: it flagged correct banners (``empty_pipe()`` ->
``TestEmptyPipe``, ``ThreadedServer.signal_handler()`` ->
``TestSignalHandlerBehaviour``) because the two are related by meaning, not by
substring.  So this gate asserts only the two properties that ARE mechanical:
a banner is followed by something, and a file does not carry the same banner
twice.  The rest is review.
"""

import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent

#: The exact shape the suite uses: a rule line, one comment line, a rule line.
_BANNER = re.compile(r"^# -{10,}\n# (?P<title>.+)\n# -{10,}$", re.MULTILINE)

#: What may legitimately follow a banner.
_DEFINITION = re.compile(r"^(class |def |@|[A-Z_]+ *[:=])")


def _modules():
    return sorted(
        p for p in HERE.glob("test_*.py") if p.name != pathlib.Path(__file__).name
    )


def test_the_suite_still_uses_banners():
    """Non-vacuity: if the convention is abandoned, this gate must not pass by
    finding nothing to check."""
    total = sum(len(_BANNER.findall(p.read_text())) for p in _modules())
    assert total > 20, f"only {total} section banners found; is the convention gone?"


def test_no_banner_is_left_dangling():
    """A banner with no definition under it is a heading for deleted code."""
    dangling = []
    for path in _modules():
        lines = path.read_text().splitlines()
        for m in _BANNER.finditer(path.read_text()):
            title = m.group("title")
            start = path.read_text()[: m.start()].count("\n") + 3
            following = [
                line
                for line in lines[start:]
                if line.strip() and not line.startswith("#")
            ]
            if not following or not _DEFINITION.match(following[0]):
                dangling.append(f"{path.name}:{start} -> {title!r}")
    assert not dangling, (
        "section banner(s) with no definition beneath them — the code they "
        "titled was moved or deleted and the heading stayed:\n  "
        + "\n  ".join(dangling)
    )


def test_no_file_carries_the_same_banner_twice():
    """Two identical banners mean one of them titles the wrong section.

    ``test_server.py`` carried ``# PreforkServer.process_timeout()`` twice: once
    over ``TestPreforkInitTimeout`` (wrong) and once over the class that really
    does test it.
    """
    duplicated = []
    for path in _modules():
        titles = [m.group("title") for m in _BANNER.finditer(path.read_text())]
        duplicated.extend(
            f"{path.name} -> {t!r}" for t in {t for t in titles if titles.count(t) > 1}
        )
    assert not duplicated, (
        "the same section banner appears twice in one file, so at least one of "
        "them titles a section it does not describe:\n  " + "\n  ".join(duplicated)
    )
