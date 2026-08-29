import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
SUITES = HERE.parent

_BANNER = re.compile(r"^# -{10,}\n# (?P<title>.+)\n# -{10,}$", re.MULTILINE)

_DEFINITION = re.compile(r"^(class |def |@|[A-Z_]+ *[:=])")

_SYMBOLISH = re.compile(r"[a-z]_[a-z]|[a-z][A-Z]")


def _modules():
    return sorted(
        p
        for p in SUITES.rglob("*.py")
        if p.name != pathlib.Path(__file__).name and "__pycache__" not in p.parts
    )


def _sources():
    return [(p, t, t.splitlines()) for p in _modules() for t in (p.read_text(),)]


def _banner_symbols(title: str) -> list[str]:
    head = re.split(r"\s+[—-]\s+", title)[0]
    words = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", head)
    return [
        w for w in words if _SYMBOLISH.search(w) or f"{w}(" in head or f"{w}." in head
    ]


def test_the_suite_still_uses_banners():
    total = sum(len(_BANNER.findall(t)) for _, t, _ in _sources())
    assert total > 20, f"only {total} section banners found; is the convention gone?"


def test_no_banner_is_left_dangling():
    dangling = []
    for path, text, lines in _sources():
        for m in _BANNER.finditer(text):
            start = text[: m.start()].count("\n") + 3
            following = [
                line
                for line in lines[start:]
                if line.strip() and not line.startswith("#")
            ]
            if not following or not _DEFINITION.match(following[0]):
                dangling.append(f"{path.name}:{start + 1} -> {m.group('title')!r}")
    assert not dangling, (
        "section banner(s) with no definition beneath them — the code they "
        "titled was moved or deleted and the heading stayed:\n  "
        + "\n  ".join(dangling)
    )


def test_every_banner_names_something_beneath_it():
    stranded = []
    for path, text, _ in _sources():
        marks = list(_BANNER.finditer(text))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            section = text[m.end() : end]
            symbols = _banner_symbols(m.group("title"))
            if symbols and not any(sym in section for sym in symbols):
                line = text[: m.start()].count("\n") + 2
                stranded.append(
                    f"{path.name}:{line} -> {m.group('title')!r}\n"
                    f"      names {symbols}, none of which appears beneath it"
                )
    assert not stranded, (
        "section banner(s) naming a symbol that occurs nowhere in the section "
        "they head — the code moved and the heading stayed:\n  " + "\n  ".join(stranded)
    )


def test_no_file_carries_the_same_banner_twice():
    duplicated = []
    for path, text, _ in _sources():
        titles = [m.group("title") for m in _BANNER.finditer(text)]
        duplicated.extend(
            f"{path.name} -> {t!r}" for t in {t for t in titles if titles.count(t) > 1}
        )
    assert not duplicated, (
        "the same section banner appears twice in one file, so at least one of "
        "them titles a section it does not describe:\n  " + "\n  ".join(duplicated)
    )


def test_the_correspondence_check_is_not_vacuous():
    assert _banner_symbols("ThreadedServer.process_limit()") == [
        "ThreadedServer",
        "process_limit",
    ]
    assert _banner_symbols("empty_pipe()") == ["empty_pipe"]
    assert _banner_symbols("WorkerCron.sleep() — idle select") == [
        "WorkerCron",
        "sleep",
    ]
    assert _banner_symbols("_cron.order_notified_first — dedup") == [
        "_cron",
        "order_notified_first",
    ]
    assert _banner_symbols("Infrastructure fixtures") == []
    assert _banner_symbols("Socket activation: IPv6 family detection") == []
    assert _banner_symbols("The wiring each backend depends on — recursion") == []
