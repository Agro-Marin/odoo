# ``slug`` is deliberately NOT registered in ``odoo.tools.rendering_tools``'s
# ``template_env_globals`` here. This module used to inject
# ``lambda value: request.env["ir.http"]._slug(value)`` into that dict at import
# time, which was both redundant and a live bug:
#
# * Redundant — every renderer that can evaluate ``slug(...)`` already binds it
#   from the env, with no request needed: ``http_routing``'s ``ir.qweb``
#   ``_prepare_environment`` for view rendering, and ``mail``'s
#   ``MixinMailRender._render_eval_context`` for mail templates.
# * A bug — ``template_env_globals`` has exactly one consumer,
#   ``_render_eval_context``, and it merges the dict *after* setting its own
#   ``slug``, so the request-bound lambda silently won. Any render with no HTTP
#   request bound (the ``ir.cron`` mail schedulers, queued mail, a server
#   action) then raised ``RuntimeError: object is not bound`` from inside
#   ``safe_eval``, which ``mail.template`` swallows into a generic "could not
#   render" — a template with ``{{ slug(object) }}`` (e.g. ``event``'s
#   reminders) failed with no usable diagnostic.
#
# Mutating another module's global dict at import time is also not undone on
# uninstall. If a future renderer needs ``slug`` it should bind it from its own
# env, like the two above do.

from . import controllers
from . import models
from . import utils
from . import wizard
