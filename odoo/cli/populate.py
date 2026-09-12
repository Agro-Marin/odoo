import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from odoo.libs.debug_log import DebugLog
from odoo.logutils import RUNBOT
from odoo.tools.populate import populate_models

from . import DatabaseCommand, open_environment

if TYPE_CHECKING:
    from odoo import api

DEFAULT_FACTOR = "10000"
DEFAULT_SEPARATOR = "_"
DEFAULT_MODELS = "res.partner,product.template,account.move,sale.order,crm.lead,stock.picking,project.task"

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)


def _prepare_factors_by_model_name(
    factors: str, models: str, error: Callable[[str], None]
) -> dict[str, int]:
    try:
        opt_factors = [int(f) for f in factors.split(",")]
    except ValueError:
        _debug.logic("cli.populate.factors_rejected", reason="not_integers")
        error(f"--factors must be a comma-separated list of integers, got {factors!r}")
        return {}
    if any(f < 1 for f in opt_factors):
        _debug.logic("cli.populate.factors_rejected", reason="below_one")
        error(f"--factors must all be >= 1, got {factors!r}")
        return {}
    model_names = models.split(",")
    _debug.logic(
        "cli.populate.factors",
        models=len(model_names),
        factors=len(opt_factors),
        propagated=max(len(model_names) - len(opt_factors), 0),
    )
    if len(opt_factors) > len(model_names):
        _logger.warning(
            "%d factors provided for %d models; ignoring the extra factors %s",
            len(opt_factors),
            len(model_names),
            opt_factors[len(model_names) :],
        )
    return {
        model_name: (
            opt_factors[index] if index < len(opt_factors) else opt_factors[-1]
        )
        for index, model_name in enumerate(model_names)
    }


class Populate(DatabaseCommand):
    description = (
        "Populate database via duplication of existing data for testing/demo purposes"
    )

    def __init__(self) -> None:
        super().__init__()
        parser = self.parser
        self.add_config_arguments(parser)
        parser.add_argument(
            "--factors",
            dest="factors",
            help="Comma-separated factors, one per model, or a single factor "
            "(a factor of 3 copies the model 3 times, reaching 4x its original "
            "size). The last factor propagates to any remaining models.",
            default=DEFAULT_FACTOR,
        )
        parser.add_argument(
            "--models",
            dest="models_to_populate",
            help="Comma separated list of models",
            default=DEFAULT_MODELS,
        )
        parser.add_argument(
            "--sep",
            dest="separator",
            help="Single character separator for char/text fields.",
            default=DEFAULT_SEPARATOR,
        )

    def run(self, cmdargs: list[str]) -> None:
        parser = self.parser
        parsed_args, unknown = self.parse_args(cmdargs)

        db_name = self.bootstrap_config(parsed_args, extra_args=unknown)
        model_factors = _prepare_factors_by_model_name(
            parsed_args.factors, parsed_args.models_to_populate, parser.error
        )
        if len(parsed_args.separator) != 1:
            _debug.logic(
                "cli.populate.separator_rejected", length=len(parsed_args.separator)
            )
            parser.error(
                f"--sep must be a single Unicode character, got "
                f"{parsed_args.separator!r} (length {len(parsed_args.separator)})"
            )
        separator_code = ord(parsed_args.separator)

        with open_environment(db_name, context={"active_test": False}) as env:
            self._populate_models_named(env, model_factors, separator_code)

    @classmethod
    def _populate_models_named(
        cls,
        env: api.Environment,
        model_name_factors: dict[str, int],
        separator_code: int,
    ) -> None:
        model_factors = {
            model: factor
            for model_name, factor in model_name_factors.items()
            if (model := env.get(model_name)) is not None
            and not (model._transient or model._abstract)
        }
        if skipped := set(model_name_factors) - {m._name for m in model_factors}:
            _debug.logic("cli.populate.models_skipped", count=len(skipped))
            _logger.warning(
                "Ignoring unknown, transient or abstract models: %s",
                ", ".join(sorted(skipped)),
            )
        _logger.log(RUNBOT, "Populating models %s", list(model_factors))
        t0 = time.time()
        with _debug.perf(
            "cli.populate",
            cr=env.cr,
            models=len(model_factors),
            skipped=len(skipped) if skipped else 0,
            separator=separator_code,
        ):
            with _debug.perf("cli.populate.models", cr=env.cr):
                populate_models(model_factors, separator_code)
            with _debug.perf("cli.populate.flush", cr=env.cr):
                env.flush_all()
        model_time = time.time() - t0
        _logger.info(
            "Populated models %s (total: %fs)", list(model_factors), model_time
        )
