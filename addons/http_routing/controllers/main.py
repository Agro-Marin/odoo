# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.session import Session
from odoo.addons.web.controllers.webclient import WebClient

_logger = logging.getLogger(__name__)


class Routing(Home):
    @http.route(
        "/website/translations",
        type="http",
        auth="public",
        website=True,
        readonly=True,
        sitemap=False,
    )
    def get_website_translations(self, hash=None, lang=None, mods=None):
        """Serve the web translations of the *frontend* modules.

        ``mods`` is accepted for backward compatibility but deliberately
        ignored. The module list is the server-side allow-list
        :meth:`~odoo.addons.http_routing.models.ir_http.IrHttp.get_translation_frontend_modules`,
        which modules extend through ``_get_translation_frontend_modules_name``
        / ``_get_translation_frontend_modules_domain`` -- that hook, not a query
        parameter, is how a module opts its translations into the public bundle.

        Appending a caller-supplied list to it (the previous behaviour) let an
        anonymous visitor choose the cache key of
        ``ir.http._get_web_translations_hash``, which is ``ormcache``d on
        ``frozenset(modules)`` in the *shared* 8192-slot "default" LRU -- the
        one also holding ``_xmlid_lookup``, ``_get_group_ids`` and the rest of
        the registry's ACL/record-rule lookups. Measured here: exactly one new
        entry per distinct ``mods`` value, ~19 ms of server CPU per miss, so a
        few thousand unauthenticated ``?mods=<random>`` hits both burn CPU and
        evict every co-tenant of that LRU, indefinitely.

        (The read itself is not much of a disclosure: ``get_web_translations``
        loads a module's ``.po`` files off the addons path whether or not the
        module is installed, so ``mods`` cannot enumerate the installed set, and
        stock Odoo translations are public anyway. A *custom* addon's UI strings
        are another matter.)

        The web client (``@web/core/l10n/localization_service``) only ever sends
        ``hash``/``lang``; nothing in the tree sends ``mods``.
        """
        IrHttp = request.env["ir.http"].sudo()
        modules = IrHttp.get_translation_frontend_modules()
        if mods:
            _logger.debug(
                "Ignoring caller-supplied mods=%r on %s; serving %s",
                mods,
                request.httprequest.path,
                modules,
            )
        return WebClient().translations(hash, mods=",".join(modules), lang=lang)


class SessionWebsite(Session):
    @http.route("/web/session/logout", website=True, multilang=False, sitemap=False)
    def logout(self, redirect="/odoo"):
        return super().logout(redirect=redirect)
