from odoo import tools
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestUi(HttpCase):
    @tools.mute_logger("odoo.http")
    def test_01_point_of_sale_tour(self):

        self.start_tour("/odoo", "point_of_sale_tour", login="admin")
