import argparse
import os
import re
import sys
from collections.abc import Generator
from pathlib import Path

import jinja2

from . import Command


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

    def run(self, cmdargs: list[str]) -> None:
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

        args = parser.parse_args(args=cmdargs)

        try:
            params = args.template.parse_params(args.name)
        except ValueError as err:
            parser.error(str(err))
        args.template.render_to(
            args.template.modname_for(args.name, params),
            directory(args.dest, create=True),
            params=params,
        )


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


# S701: scaffold renders Python/XML/CSV SOURCE files, not HTML — autoescaping
# would HTML-escape the generated code and corrupt every scaffolded module.
_env = jinja2.Environment()  # noqa: S701  see comment above
_env.filters["snake"] = snake
_env.filters["pascal"] = pascal


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

        Most templates need only ``{'name': name}``; specialised ones (e.g.
        ``l10n_payroll``, encoding a country and locale code) override here.

        :raises ValueError: on malformed input
        """
        if self.id == "l10n_payroll":
            if "-" not in name:
                raise ValueError(
                    "l10n_payroll template requires a name of the form "
                    f"'<country>-<code>' (e.g. 'mexico-mx'); got {name!r}"
                )
            country, _, code = name.partition("-")
            return {"name": country, "code": code}
        return {"name": name}

    def modname_for(self, name: str, params: dict[str, str]) -> str:
        """Resolve the on-disk module directory name from ``name``/``params``.

        Mirrors ``parse_params``: same special-cases. Keeping both here means a
        new template naming convention touches one class.
        """
        if self.id == "l10n_payroll":
            return f"l10n_{params['code']}_hr_payroll"
        return snake(name)

    def render_to(
        self, modname: str, directory: Path, params: dict[str, str] | None = None
    ) -> None:
        """Render this module template to ``directory`` with the provided
        rendering parameters.
        """
        for path, content in self.files():
            rendered = Path(_env.from_string(str(path)).render(params))
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
                    _env.from_string(content.decode("utf-8")).stream(params or {}).dump(
                        f, encoding="utf-8"
                    )
                    f.write(b"\n")
