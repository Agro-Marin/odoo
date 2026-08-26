import argparse
import dataclasses
import functools
import os
import re
import sys
from collections.abc import Callable, Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import Command

if TYPE_CHECKING:
    from jinja2 import Environment
else:
    Environment = Any


class Scaffold(Command):
    """Generates an Odoo module skeleton."""

    def __init__(self) -> None:
        super().__init__()
        try:
            templates = sorted(d.name for d in _builtins_dir().iterdir() if d.is_dir())
        except OSError:
            templates = []
        self.epilog = (
            f"Built-in templates available are: {', '.join(templates)}"
            if templates
            else "No built-in templates found (templates/ directory missing)."
        )
        parser = self.parser
        parser.add_argument(
            "-t",
            "--template",
            type=Template,
            default="default",
            help="Use a custom module template, can be a template name or the"
            " path to a module template (default: %(default)s)",
        )
        parser.add_argument("name", help="Name of the module to create")
        parser.add_argument(
            "dest",
            default=".",
            nargs="?",
            help="Directory to create the module in (default: %(default)s)",
        )
        parser.add_argument(
            "--force",
            "-f",
            action="store_true",
            help="Overwrite an existing module directory instead of refusing",
        )

    def run(self, cmdargs: list[str]) -> None:
        parser = self.parser
        args = parser.parse_args(args=cmdargs)

        try:
            params = args.template.parse_params(args.name)
        except ValueError as err:
            parser.error(str(err))
        modname = args.template.modname_for(args.name, params)
        dest = directory(args.dest, create=True)
        if not args.force and (dest / modname).exists():
            parser.error(f"{dest / modname} already exists; pass --force to overwrite it")
        args.template.render_to(modname, dest, params=params)


def _builtins_dir(*parts: str) -> Path:
    """Return the path to the built-in templates directory."""
    base = Path(__file__).resolve().parent / "templates"
    return base / Path(*parts) if parts else base


def snake(s: str) -> str:
    """Convert ``s`` to snake_case, including initialisms.

    Examples:
        FooBar     -> foo_bar
        APITest    -> api_test
        APIMyTest  -> api_my_test
        HTTPServer -> http_server
    """
    s = re.sub(r"(?<=[A-Z])([A-Z][a-z])", r" \1", s)
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r" \1", s)
    return "_".join(s.lower().split())


def pascal(s: str) -> str:
    """Convert ``s`` to PascalCase."""
    return "".join(ss.capitalize() for ss in re.sub(r"[_\s]+", " ", s).split())


def directory(p: str, create: bool = False) -> Path:
    """Resolve and validate a directory path (expanding ~ and $VAR).

    :param create: create the directory if it doesn't exist
    """
    expanded = Path(os.path.expandvars(p)).expanduser().resolve()
    if create and not expanded.exists():
        expanded.mkdir(parents=True)
    if not expanded.is_dir():
        sys.exit(f"{p} is not a directory")
    return expanded


@functools.cache
def _env() -> Environment:
    """Build the Jinja environment, importing Jinja2 on first render.

    Jinja2 is not a server dependency. Nothing outside this command imports it,
    and ``cli/__init__`` loads a command module only when that command is
    dispatched — so a server process never reaches it. Keeping the import out
    of module scope is what lets ``odoo.cli.scaffold`` be *imported* without
    Jinja2 installed, which ``base``'s ``test_cli`` and ``test_lint``'s
    ``test_pep649`` both do. It is pinned in ``requirements-test.txt`` and
    offered as the ``scaffold`` extra in ``setup.py``.
    """
    try:
        import jinja2
    except ImportError:
        sys.exit(
            "odoo-bin scaffold needs Jinja2, which is not installed.\n"
            "    pip install Jinja2      (or: pip install 'odoo[scaffold]')"
        )
    env = jinja2.Environment()  # noqa: S701  see comment above
    env.filters["snake"] = snake
    env.filters["pascal"] = pascal
    return env


@dataclasses.dataclass(frozen=True)
class NamingConvention:
    """How one template turns the user's ``name`` argument into render params
    and into a module directory name.

    The two halves live in one object because they have to agree: what
    ``parse`` puts in ``params`` is what ``modname`` reads back out. They used
    to be two ``if self.id == ...`` branches in two methods of
    :class:`Template`, with a docstring asking the next person to keep them in
    step — `test_scaffold_naming_conventions_agree` asks the suite instead.
    """

    parse: Callable[[str], dict[str, str]]
    modname: Callable[[str, dict[str, str]], str]


def _parse_country_code(name: str) -> dict[str, str]:
    """``'mexico-mx'`` -> ``{'name': 'mexico', 'code': 'mx'}``."""
    if "-" not in name:
        raise ValueError(
            "l10n_payroll template requires a name of the form "
            f"'<country>-<code>' (e.g. 'mexico-mx'); got {name!r}"
        )
    country, _, code = name.partition("-")
    return {"name": country, "code": code}


DEFAULT_NAMING = NamingConvention(
    parse=lambda name: {"name": name},
    modname=lambda name, params: snake(name),
)

NAMING_CONVENTIONS = {
    "l10n_payroll": NamingConvention(
        parse=_parse_country_code,
        modname=lambda name, params: f"l10n_{params['code']}_hr_payroll",
    ),
}


class Template:
    """A module template that can be rendered into a new Odoo module."""

    def __init__(self, identifier: str) -> None:
        self.id = identifier
        self.path = _builtins_dir(identifier)
        if self.path.is_dir():
            return
        self.path = Path(identifier)
        if self.path.is_dir():
            return
        raise argparse.ArgumentTypeError(
            f"{identifier!r} is not a valid module template"
        )

    def __str__(self) -> str:
        return self.id

    def files(self) -> Generator[tuple[Path, bytes]]:
        """List the path and content of all files in the template."""
        for dirpath, _, filenames in self.path.walk():
            for f in filenames:
                filepath = dirpath / f
                yield filepath, filepath.read_bytes()

    def parse_params(self, name: str) -> dict[str, str]:
        """Parse the user-supplied ``name`` into Jinja rendering params.

        :raises ValueError: on malformed input
        """
        convention = NAMING_CONVENTIONS.get(self.id, DEFAULT_NAMING)
        return convention.parse(name)

    def modname_for(self, name: str, params: dict[str, str]) -> str:
        """Resolve the on-disk module directory name from ``name``/``params``."""
        convention = NAMING_CONVENTIONS.get(self.id, DEFAULT_NAMING)
        return convention.modname(name, params)

    def render_to(
        self, modname: str, directory: Path, params: dict[str, str] | None = None
    ) -> None:
        """Render this module template to ``directory`` with the provided
        rendering parameters.
        """
        env = _env()
        for path, content in self.files():
            rendered = Path(env.from_string(str(path)).render(params))
            local = rendered.relative_to(self.path)
            ext = rendered.suffix
            if ext == ".template":
                local = local.with_suffix("")
            dest = Path(directory) / modname / local
            dest.parent.mkdir(parents=True, exist_ok=True)

            with dest.open("wb") as f:
                if ext not in (
                    ".py",
                    ".xml",
                    ".csv",
                    ".js",
                    ".rst",
                    ".html",
                    ".template",
                ):
                    f.write(content)
                else:
                    env.from_string(content.decode("utf-8")).stream(params or {}).dump(
                        f, encoding="utf-8"
                    )
                    f.write(b"\n")
