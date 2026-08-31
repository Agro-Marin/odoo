from . import models
from . import report


def _pos_sale_post_init(env):
    env['pos.config']._update_downpayment_product()
