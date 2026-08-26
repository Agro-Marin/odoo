import sys

from odoo.tools import cloc

from . import DatabaseCommand


class Cloc(DatabaseCommand):
    """Count lines of code per modules"""

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
        # `-c`/`-d`/`-D` come from DatabaseCommand rather than three private
        # copies with their own help strings; `-d` here is what every other
        # command spells `-d`, so a config file's `db_name` reaches cloc too.
        self.add_config_arguments(self.parser)
        self.parser.add_argument(
            "--path", "-p", action="append", help="File or directory path"
        )
        self.parser.add_argument("--verbose", "-v", action="store_true")

    def run(self, args: list[str]) -> None:
        opt, unknown = self.parse_args(args)
        counter = cloc.Cloc()

        # A `--path` run needs no database and must not adopt the one a config
        # file happens to name, so it only reads the config when `-d` opts in.
        # With no `--path` the config IS consulted: `cloc -c prod.conf` counts
        # the database that file names, like every other command. The guard
        # this replaces ran before the config was parsed, so a `db_name` in the
        # file could only ever produce a usage error.
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
