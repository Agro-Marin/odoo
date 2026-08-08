"""The default-password warning must not be able to fail a successful login.

``_admin_password_warn`` runs from ``_login_redirect``, i.e. after
authentication has already succeeded. It parsed ``remote_addr`` unguarded, so a
client address the ``ipaddress`` module rejects turned a working login into a
500 -- session created, user authenticated, error page served. Under
``proxy_mode`` that address is whatever the proxy put in ``X-Forwarded-For``,
including the ``unknown`` nodename RFC 7239 allows.
"""

from odoo.tests import BaseCase, tagged

from ..controllers.home import _is_private_address


@tagged("-at_install", "post_install")
class TestAdminPasswordWarnAddress(BaseCase):
    def test_private_addresses_are_recognised(self):
        for address in ("127.0.0.1", "10.1.2.3", "192.168.0.7", "::1", "fd00::1"):
            with self.subTest(address=address):
                self.assertTrue(_is_private_address(address))

    def test_public_addresses_are_recognised(self):
        # Deliberately not the documentation ranges (192.0.2/24, 198.51.100/24,
        # 203.0.113/24): since Python 3.13 ``is_private`` reports those as
        # private, so they would pass this test for the wrong reason.
        for address in ("8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"):
            with self.subTest(address=address):
                self.assertFalse(_is_private_address(address))

    def test_unparsable_addresses_do_not_raise(self):
        """The regression itself: each of these used to raise ValueError.

        They resolve to "not private", which lets the warning through -- the safe
        direction for a warning about being exposed to untrusted networks.
        """
        for address in (None, "", "unknown", "127.0.0.1, 10.0.0.1", "_hidden", "abc"):
            with self.subTest(address=address):
                self.assertFalse(_is_private_address(address))
