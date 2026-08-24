# -*- coding: utf-8 -*-
from . import models


def _post_init_hook(env):
    env['res.groups']._activate_group_account_secured()
