import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from odoo.tools.populate import populate_models

from . import DatabaseCommand, odoo_env

if TYPE_CHECKING:
    from odoo import api

# argparse delivers every user-supplied value as `str`; keep the default in
# the same type so comparisons and .split() behave uniformly.
DEFAULT_FACTOR = "10000"
DEFAULT_SEPARATOR = "_"
DEFAULT_MODELS = "res.partner,product.template,account.move,sale.order,crm.lead,stock.picking,project.task"

_logger = logging.getLogger(__name__)


def _parse_model_factors(
    factors: str, models: str, error: Callable[[str], None]
) -> dict[str, int]:
    """Map each model name to its factor.

    The last factor propagates to the remaining models; surplus factors are
    reported (they usually mean a typo in --models) but tolerated.

    :param factors: comma-separated ints, e.g. ``"3"`` or ``"3,5"``
    :param models: comma-separated model names
    :param error: argparse-style error callback (NoReturn in practice)
    """
    try:
        opt_factors = [int(f) for f in factors.split(",")]
    except ValueError:
        error(f"--factors must be a comma-separated list of integers, got {factors!r}")
        # argparse's parser.error never returns; guard the fall-through for
        # callbacks that do (tests, programmatic use).
        return {}
    if any(f < 1 for f in opt_factors):
        # A factor of N *copies* the data N times; 0/negative would silently
        # populate nothing while the command still reports success.
        error(f"--factors must all be >= 1, got {factors!r}")
        return {}
    model_names = models.split(",")
    if len(opt_factors) > len(model_names):
        _logger.warning(
            "%d factors provided for %d models; ignoring the extra factors %s",
            len(opt_factors),
            len(model_names),
            opt_factors[len(model_names) :],
        )
    # deduplicate models if necessary, keeping the last factor of each model
    return {
        model_name: (
            opt_factors[index] if index < len(opt_factors) else opt_factors[-1]
        )
        for index, model_name in enumerate(model_names)
    }


class Populate(DatabaseCommand):
    """Populate database via duplication of existing data for testing/demo purposes"""

    def run(self, cmdargs: list[str]) -> None:
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
        parsed_args = parser.parse_args(cmdargs)

        db_name = self.bootstrap_config(parsed_args)
        model_factors = _parse_model_factors(
            parsed_args.factors, parsed_args.models_to_populate, parser.error
        )
        if len(parsed_args.separator) != 1:
            parser.error(
                f"--sep must be a single Unicode character, got "
                f"{parsed_args.separator!r} (length {len(parsed_args.separator)})"
            )
        separator_code = ord(parsed_args.separator)

        with odoo_env(db_name, context={"active_test": False}) as env:
            self.populate(env, model_factors, separator_code)

    @classmethod
    def populate(
        cls,
        env: api.Environment,
        modelname_factors: dict[str, int],
        separator_code: int,
    ) -> None:
        """Populate models with synthetic data."""
        model_factors = {
            model: factor
            for model_name, factor in modelname_factors.items()
            if (model := env.get(model_name)) is not None
            and not (model._transient or model._abstract)
        }
        # Warn on dropped models; previously they vanished silently and the
        # command still reported success.
        if skipped := set(modelname_factors) - {m._name for m in model_factors}:
            _logger.warning(
                "Ignoring unknown, transient or abstract models: %s",
                ", ".join(sorted(skipped)),
            )
        _logger.log(logging.RUNBOT, "Populating models %s", list(model_factors))
        t0 = time.time()
        populate_models(model_factors, separator_code)
        env.flush_all()
        model_time = time.time() - t0
        _logger.info(
            "Populated models %s (total: %fs)", list(model_factors), model_time
        )
