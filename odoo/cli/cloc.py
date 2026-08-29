import sys

from odoo.tools import cloc

from . import DatabaseCommand


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

        if opt.db_name or not opt.path:
            db_name = self.bootstrap_config(opt, allow_none=True, extra_args=unknown)
            if db_name is None:
                self.parser.print_help(sys.stderr)
                sys.exit(2)
            counter.count_database(db_name)
        if opt.path:
            for path in dict.fromkeys(opt.path):
                counter.count_path(path)
        print(counter.report(opt.verbose))
