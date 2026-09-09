import logging
from datetime import datetime

from dateutil.relativedelta import relativedelta
from requests import PreparedRequest, Response, Session

import odoo.tests

from odoo.addons.base.tests.common import HttpCaseWithUserDemo

_logger = logging.getLogger(__name__)

CLICKBOT_SUCCESS_SIGNAL = "clickbot test succeeded"
CLICKBOT_FAILURE_SIGNAL = "clickbot test failed"


def _clickbot_error_checker(message):
    """Let the clickbot deliver its own verdict.

    The bot logs every broken menu and keeps going, then ends the run with
    either the success signal or the failure one. Settling on the first
    console error -- the error service's traceback, which arrives before the
    bot has even seen the error dialog -- would stop the run at the first
    broken app and leave every other one untested, which is the whole point of
    letting it continue. The bot counts uncaught errors too, so nothing a
    console error would have caught is lost: it comes back as the failure
    signal at the end, with all of them named above it.
    """
    return CLICKBOT_FAILURE_SIGNAL in message


@odoo.tests.tagged("click_all", "post_install", "-at_install", "-standard")
class TestMenusAdmin(odoo.tests.HttpCase):
    allow_end_on_form = True

    @classmethod
    def _request_handler(cls, s: Session, r: PreparedRequest, /, **kw):
        if "proxy/v1/get_dashboard_institutions" in r.url:
            r = Response()
            r.status_code = 200
            r.json = lambda: {"result": {}}
            return r
        return super()._request_handler(s, r, **kw)

    def test_01_click_everywhere_as_admin(self):
        if "tour_enabled" in self.env["res.users"]._fields:
            self.env.ref("base.user_admin").tour_enabled = False
        menus = self.env["ir.ui.menu"].load_menus(False)
        for app_id in menus["root"]["children"]:
            with self.subTest(app=menus[app_id]["name"]):
                _logger.runbot("Testing %s", menus[app_id]["name"])
                self.browser_js(
                    "/odoo",
                    "odoo.loader.modules.get('@web/webclient/clickbot/clickbot_loader').startClickEverywhere('%s');"
                    % menus[app_id]["xmlid"],
                    "odoo.isReady === true",
                    login="admin",
                    timeout=1200,
                    success_signal=CLICKBOT_SUCCESS_SIGNAL,
                    error_checker=_clickbot_error_checker,
                )


@odoo.tests.tagged("click_all", "post_install", "-at_install", "-standard")
class TestMenusDemo(HttpCaseWithUserDemo):
    def test_01_click_everywhere_as_demo(self):
        user_demo = self.user_demo
        menus = self.env["ir.ui.menu"].with_user(user_demo.id).load_menus(False)
        for app_id in menus["root"]["children"]:
            with self.subTest(app=menus[app_id]["name"]):
                _logger.runbot("Testing %s", menus[app_id]["name"])
                self.browser_js(
                    "/odoo",
                    "odoo.loader.modules.get('@web/webclient/clickbot/clickbot_loader').startClickEverywhere('%s');"
                    % menus[app_id]["xmlid"],
                    "odoo.isReady === true",
                    login="demo",
                    timeout=1200,
                    success_signal=CLICKBOT_SUCCESS_SIGNAL,
                    error_checker=_clickbot_error_checker,
                )


@odoo.tests.tagged("post_install", "-at_install", "web_tour")
class TestMenusAdminLight(odoo.tests.HttpCase):
    @classmethod
    def _request_handler(cls, s: Session, r: PreparedRequest, /, **kw):
        if "proxy/v2/get_dashboard_institutions" in r.url:
            r = Response()
            r.status_code = 200
            r.json = list
            return r
        return super()._request_handler(s, r, **kw)

    def test_01_click_apps_menus_as_admin(self):
        if "tour_enabled" in self.env["res.users"]._fields:
            self.env.ref("base.user_admin").tour_enabled = False
        if "pos.prep.display" in self.env:
            self.env["pos.prep.display"].create(
                {
                    "name": "Super Smart Kitchen Display",
                }
            )
        if "project.task" in self.env and "is_fsm" in self.env["project.task"]:
            self.env["project.task"].create(
                {
                    "name": "Zizizbroken",
                    "project_id": self.env.ref("industry_fsm.fsm_project").id,
                    "user_ids": [(4, self.env.ref("base.user_admin").id)],
                    "date_deadline": datetime.now() + relativedelta(hour=12),
                    "planned_date_begin": datetime.now() + relativedelta(hour=10),
                }
            )
        self.browser_js(
            "/odoo",
            "odoo.loader.modules.get('@web/webclient/clickbot/clickbot_loader').startClickEverywhere(undefined, true);",
            "odoo.isReady === true",
            login="admin",
            timeout=120,
            success_signal=CLICKBOT_SUCCESS_SIGNAL,
            error_checker=_clickbot_error_checker,
        )


@odoo.tests.tagged("post_install", "-at_install", "web_tour")
class TestMenusDemoLight(HttpCaseWithUserDemo):
    def test_01_click_apps_menus_as_demo(self):
        if "tour_enabled" in self.env["res.users"]._fields:
            self.user_demo.tour_enabled = False
        group_website_designer = self.env.ref(
            "website.group_website_designer", raise_if_not_found=False
        )
        if group_website_designer:
            self.env.ref("base.group_user").write(
                {"implied_ids": [(4, group_website_designer.id)]}
            )
        self.browser_js(
            "/odoo",
            "odoo.loader.modules.get('@web/webclient/clickbot/clickbot_loader').startClickEverywhere(undefined, true);",
            "odoo.isReady === true",
            login="demo",
            timeout=120,
            success_signal=CLICKBOT_SUCCESS_SIGNAL,
            error_checker=_clickbot_error_checker,
        )
