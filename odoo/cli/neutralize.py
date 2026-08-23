import logging
import sys

import odoo.db
import odoo.modules.neutralize

from . import DatabaseCommand

_logger = logging.getLogger(__name__)


class Neutralize(DatabaseCommand):
    """Neutralize a production database for testing: no emails sent, etc."""

    def __init__(self) -> None:
        super().__init__()
        self.add_config_arguments(self.parser)
        self.parser.add_argument(
            "--stdout",
            action="store_true",
            dest="to_stdout",
            help="Output the neutralization SQL instead of applying it",
        )

    def run(self, args: list[str]) -> None:
        parsed_args, unknown = self.parse_args(args)
        dbname = self.bootstrap_config(parsed_args, extra_args=unknown)

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
