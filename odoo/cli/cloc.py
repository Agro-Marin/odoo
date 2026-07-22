import sys

from odoo.tools import cloc, config

from . import Command, build_config_args, get_single_database


class Cloc(Command):
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

    def run(self, args: list[str]) -> None:
        self.parser.add_argument(
            "--database", "-d", dest="database", help="Database name"
        )
        self.parser.add_argument(
            "--path", "-p", action="append", help="File or directory path"
        )
        # Declared (not just forwarded via unknown args) so they show up in
        # --help; both only matter in database mode.
        self.parser.add_argument(
            "-c", "--config", dest="config", help="use a specific configuration file"
        )
        self.parser.add_argument(
            "-D",
            "--data-dir",
            dest="data_dir",
            help="directory where to store Odoo data",
        )
        self.parser.add_argument("--verbose", "-v", action="count", default=0)
        opt, unknown = self.parser.parse_known_args(args)
        if not opt.database and not opt.path:
            self.parser.print_help(sys.stderr)
            sys.exit(2)

        c = cloc.Cloc()
        if opt.database:
            # build_config_args adds --no-http; remaining unknown args (e.g.
            # --addons-path) are forwarded to the config parser, which
            # rejects genuine typos.
            if opt.data_dir:
                unknown = ["-D", opt.data_dir, *unknown]
            config.parse_config(
                build_config_args(opt.config, db_name=opt.database, extra_args=unknown),
                setup_logging=True,
            )
            db_name = get_single_database(
                config["db_name"],
                error_handler=self.parser.error,
            )
            c.count_database(db_name)
        if opt.path:
            for i in opt.path:
                c.count_path(i)
        print(c.report(opt.verbose))
