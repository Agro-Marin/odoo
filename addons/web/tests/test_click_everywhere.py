import logging
from datetime import datetime

from dateutil.relativedelta import relativedelta
from requests import PreparedRequest, Response, Session

import odoo.tests

from odoo.addons.base.tests.common import HttpCaseWithUserDemo

_logger = logging.getLogger(__name__)


@odoo.tests.tagged("click_all", "post_install", "-at_install", "-standard")
class TestMenusAdmin(odoo.tests.HttpCase):
    allow_end_on_form = True

    @classmethod
    def _request_handler(cls, s: Session, r: PreparedRequest, /, **kw):
        # mock odoofin requests
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
                    success_signal="clickbot test succeeded",
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
                    success_signal="clickbot test succeeded",
                )


@odoo.tests.tagged("post_install", "-at_install", "web_tour")
class TestMenusAdminLight(odoo.tests.HttpCase):
    @classmethod
    def _request_handler(cls, s: Session, r: PreparedRequest, /, **kw):
        # mock odoofin requests
        if "proxy/v2/get_dashboard_institutions" in r.url:
            r = Response()
            r.status_code = 200
            r.json = list
            return r
        return super()._request_handler(s, r, **kw)

    def test_01_click_apps_menus_as_admin(self):
        # Disable onboarding tours to remove warnings
        if "tour_enabled" in self.env["res.users"]._fields:
            self.env.ref("base.user_admin").tour_enabled = False
        # Without a pos.prep.display record, clicking "Kitchen Display" triggers
        # action_pos_preparation_display_kitchen_display, which opens the display
        # UI instead of a normal view — the crawler tour has nothing to click and
        # times out. Pre-creating one keeps the menu on a regular action.
        if "pos.prep.display" in self.env:
            self.env["pos.prep.display"].create(
                {
                    "name": "Super Smart Kitchen Display",
                }
            )
        # Field Service (without demo data) errors when clicking Studio: the
        # KanbanEditorRenderer's synthetic single-record group has no groupByField
        # set (there is nothing to group by), and the Studio code assumes it is
        # always defined. Seeding a task avoids that empty-group path.
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
            success_signal="clickbot test succeeded",
        )


@odoo.tests.tagged("post_install", "-at_install", "web_tour")
class TestMenusDemoLight(HttpCaseWithUserDemo):
    def test_01_click_apps_menus_as_demo(self):
        # Disable onboarding tours to remove warnings
        if "tour_enabled" in self.env["res.users"]._fields:
            self.user_demo.tour_enabled = False
        # Without this group, landing on the website dashboard (as in demo data)
        # redirects to / and crashes the test.
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
            success_signal="clickbot test succeeded",
        )
