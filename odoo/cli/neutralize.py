import logging
import sys

import odoo.db
import odoo.modules.neutralize

from . import DatabaseCommand

_logger = logging.getLogger(__name__)


class Neutralize(DatabaseCommand):
    """Neutralize a production database for testing: no emails sent, etc."""

    def run(self, args: list[str]) -> None:
        parser = self.parser
        self.add_config_arguments(parser)
        parser.add_argument(
            "--stdout",
            action="store_true",
            dest="to_stdout",
            help="Output the neutralization SQL instead of applying it",
        )
        parsed_args = parser.parse_args(args)

        dbname = self.bootstrap_config(parsed_args)

        # Python logging writes to stderr; it does not contaminate the SQL
        # emitted to stdout in --stdout mode, so log unconditionally.
        _logger.info("Starting %s database neutralization", dbname)

        try:
            with odoo.db.db_connect(dbname).cursor() as cursor:
                if parsed_args.to_stdout:
                    installed_modules = odoo.modules.neutralize.get_installed_modules(
                        cursor
                    )
                    queries = odoo.modules.neutralize.get_neutralization_queries(
                        installed_modules
                    )
                    print("BEGIN;")
                    for query in queries:
                        print(query.rstrip(";") + ";")
                    print("COMMIT;")
                else:
                    odoo.modules.neutralize.neutralize_database(cursor)

        except Exception:
            _logger.critical(
                "An error occurred during the neutralization. THE DATABASE IS NOT NEUTRALIZED!",
                exc_info=True,
            )
            sys.exit(1)
