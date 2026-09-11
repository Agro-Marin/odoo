from . import models
from . import reports


def _pos_sale_post_init(env):
    env["pos.config"]._update_downpayment_product()
