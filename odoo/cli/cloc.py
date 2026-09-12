import sys

from odoo.libs.debug_log import DebugLog
from odoo.tools import cloc

from . import DatabaseCommand

_debug = DebugLog(__name__)


class Cloc(DatabaseCommand):
    description = """
        Odoo cloc is a tool to count the number of relevant lines written
        in Python, Javascript or XML. This can be used as rough metric for
        pricing maintenance of customizations.

        It has two modes of operation, which can be combined in one
        invocation and are merged into a single report: by providing a path:

            odoo-bin cloc -p module_path

        Or by providing the name of a database:

            odoo-bin --addons-path=dirs cloc -d database

        In the latter mode, only the custom code is accounted for.
    """

    def __init__(self) -> None:
        super().__init__()
        self.add_config_arguments(self.parser)
        self.parser.add_argument(
            "--path", "-p", action="append", help="File or directory path"
        )
        self.parser.add_argument("--verbose", "-v", action="store_true")

    def run(self, args: list[str]) -> None:
        opt, unknown = self.parse_args(args)
        counter = cloc.Cloc()

        _debug.logic(
            "cli.cloc.mode",
            database=bool(opt.db_name),
            paths=len(opt.path) if opt.path else 0,
            verbose=opt.verbose,
        )
        if opt.db_name or not opt.path:
            db_name = self.bootstrap_config(opt, allow_none=True, extra_args=unknown)
            if db_name is None:
                _debug.logic("cli.cloc.rejected", reason="no_database_no_path")
                self.parser.print_help(sys.stderr)
                sys.exit(2)
            with _debug.perf("cli.cloc.count_database", db=db_name):
                counter.count_database(db_name)
        if opt.path:
            paths = list(dict.fromkeys(opt.path))
            if len(paths) != len(opt.path):
                _debug.logic(
                    "cli.cloc.paths_deduplicated",
                    given=len(opt.path),
                    unique=len(paths),
                )
            for path in paths:
                with _debug.perf("cli.cloc.count_path", path=path):
                    counter.count_path(path)
        _debug.pipeline(
            "cli.cloc.counted",
            modules=len(counter.modules),
            excluded=len(counter.excluded),
            errors=sum(len(items) for items in counter.errors.values()),
            code_lines=sum(counter.code.values()),
        )
        with _debug.perf("cli.cloc.report", verbose=opt.verbose):
            report = counter.report(opt.verbose)
        print(report)
