import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent

_BANNER = re.compile(r"^# -{10,}\n# (?P<title>.+)\n# -{10,}$", re.MULTILINE)

_DEFINITION = re.compile(r"^(class |def |@|[A-Z_]+ *[:=])")


def _modules():
    return sorted(
        p for p in HERE.glob("test_*.py") if p.name != pathlib.Path(__file__).name
    )


def test_the_suite_still_uses_banners():
    total = sum(len(_BANNER.findall(p.read_text())) for p in _modules())
    assert total > 20, f"only {total} section banners found; is the convention gone?"


def test_no_banner_is_left_dangling():
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
