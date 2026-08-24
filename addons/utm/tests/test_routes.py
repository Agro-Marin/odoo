import odoo.tests

from odoo.addons.base.tests.common import HttpCaseWithUserDemo


@odoo.tests.tagged('post_install', '-at_install')
class TestRoutes(HttpCaseWithUserDemo):

    def test_01_web_session_destroy(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        self.authenticate('demo', 'demo')
        res = self.url_open(url=base_url + '/web/session/destroy', json={})
        self.assertEqual(res.status_code, 200)
