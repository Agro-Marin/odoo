import sys

from odoo.tools import cloc

from . import DatabaseCommand


class Cloc(DatabaseCommand):
    """Count lines of code per modules"""

    description = """
        Odoo cloc is a tool to count the number of relevant lines written
        in Python, Javascript or XML. This can be used as rough metric for
        pricing maintenance of customizations.

        It has two modes of operation, either by providing a path:

            odoo-bin cloc -p module_path

        Or by providing the name of a database:

            odoo-bin --addons-path=dirs cloc -d database

        In the latter mode, only the custom code is accounted for.
    """

    def __init__(self) -> None:
        super().__init__()
        # `-c`/`-d`/`-D` come from DatabaseCommand rather than three private
        # copies with their own help strings; `-d` here is what every other
        # command spells `-d`, so a config file's `db_name` reaches cloc too.
        self.add_config_arguments(self.parser)
        self.parser.add_argument(
            "--path", "-p", action="append", help="File or directory path"
        )
        self.parser.add_argument("--verbose", "-v", action="count", default=0)

    def run(self, args: list[str]) -> None:
        opt, unknown = self.parse_args(args)
        if not opt.db_name and not opt.path:
            self.parser.print_help(sys.stderr)
            sys.exit(2)

        counter = cloc.Cloc()
        # A `--path` run needs no database and must not adopt the one a config
        # file happens to name; only an explicit `-d` opts into database mode.
        if opt.db_name or not opt.path:
            db_name = self.bootstrap_config(opt, extra_args=unknown)
            counter.count_database(db_name)
        if opt.path:
            for path in opt.path:
                counter.count_path(path)
        print(counter.report(opt.verbose))
