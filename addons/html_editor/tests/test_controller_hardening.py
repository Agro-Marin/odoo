# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

import odoo.tests
from odoo.tests.common import HttpCase, new_test_user
from odoo.tools.json import scriptsafe as json_safe

from odoo.addons.mail.tools import link_preview


@odoo.tests.tagged('-at_install', 'post_install')
class TestAttachmentAddUrlHardening(HttpCase):
    """``/html_editor/attachment/add_url`` issues a server-side HEAD request to
    a fully caller-supplied URL. The route is ``auth='user'``, so a PORTAL user
    reaches it, and the request used to fire BEFORE the access check -- making
    it an SSRF probe into the server's own network even for callers who were
    then refused. The raw ``requests`` exceptions also escaped to the RPC
    client, so "connection refused" and "connected" were distinguishable: a
    working internal port scanner.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        new_test_user(cls.env, login='portal_probe', groups='base.group_portal')
        cls.headers = {'Content-Type': 'application/json'}

    def _add_url(self, url):
        return self.url_open(
            '/html_editor/attachment/add_url',
            headers=self.headers,
            data=json_safe.dumps({'params': {'url': url, 'res_model': 'ir.ui.view'}}),
        ).json()

    def test_internal_url_is_refused_without_any_request(self):
        self.authenticate('admin', 'admin')
        with patch('requests.head') as mocked_head:
            response = self._add_url('http://127.0.0.1:9/internal')
        mocked_head.assert_not_called()
        self.assertIn('error', response)

    def test_link_local_metadata_address_is_refused(self):
        self.authenticate('admin', 'admin')
        with patch('requests.head') as mocked_head:
            self._add_url('http://169.254.169.254/latest/meta-data/')
        mocked_head.assert_not_called()

    def test_non_http_schemes_are_refused(self):
        self.authenticate('admin', 'admin')
        for url in ('file:///etc/passwd', 'gopher://127.0.0.1:70/x', 'not-a-url'):
            with patch('requests.head') as mocked_head:
                response = self._add_url(url)
            mocked_head.assert_not_called()
            self.assertIn('error', response, url)

    def test_portal_user_cannot_distinguish_open_from_closed_ports(self):
        """The whole point of the guard: every rejected target must produce the
        SAME response, or the error message itself is the oracle."""
        self.authenticate('portal_probe', 'portal_probe')
        messages = set()
        for url in ('http://127.0.0.1:9991/x', 'http://127.0.0.1:9992/x'):
            response = self._add_url(url)
            messages.add(response.get('error', {}).get('data', {}).get('message'))
        self.assertEqual(len(messages), 1, "internal targets are distinguishable: %s" % messages)

    def test_public_url_still_reaches_the_head_request(self):
        """The guard must not break the legitimate flow."""
        self.authenticate('admin', 'admin')
        with patch.object(link_preview, '_url_is_safe', return_value=True), \
             patch('requests.head') as mocked_head:
            mocked_head.return_value.status_code = 200
            mocked_head.return_value.headers = {'content-type': 'image/png'}
            response = self._add_url('https://example.com/image.png')
        mocked_head.assert_called_once()
        self.assertNotIn('error', response)
        self.assertEqual(response['result']['mimetype'], 'image/png')

    def test_upstream_request_failure_does_not_escape(self):
        """A network error on an allowed host must not surface a raw
        ``requests`` exception out of a jsonrpc endpoint."""
        self.authenticate('admin', 'admin')
        import requests
        with patch.object(link_preview, '_url_is_safe', return_value=True), \
             patch('requests.head', side_effect=requests.ConnectionError('boom')):
            # distinct URL: `get_existing_attachment` would otherwise hand back
            # the attachment created by the happy-path test above
            response = self._add_url('https://example.com/unreachable-media')
        # The contract is that the failure is swallowed: the attachment is still
        # created and no raw `requests` exception reaches the RPC client.
        # (Not asserted on `mimetype`: ir.attachment guesses one from the name,
        # so that field says nothing about whether the HEAD request succeeded.)
        self.assertNotIn('error', response)
        self.assertTrue(response['result']['id'])


@odoo.tests.tagged('-at_install', 'post_install')
class TestShapeIllustrationNoTraceback(HttpCase):
    """``/html_editor/shape/illustration/<id>`` is a PUBLIC route. Every
    attachment uploaded through the editor itself has ``url = False``, so
    ``attachment.url.startswith(...)`` raised AttributeError and returned an
    unauthenticated 500 -- while also making the url-lookup fallback below it
    unreachable for exactly those attachments.
    """

    def test_public_binary_attachment_without_url_is_not_a_500(self):
        attachment = self.env['ir.attachment'].create({
            'name': 'photo.png',
            'type': 'binary',
            'public': True,
            'res_model': 'ir.ui.view',
            'res_id': 0,
            'mimetype': 'image/png',
            'raw': b'\x89PNG\r\n\x1a\n' + b'0' * 32,
        })
        self.env.flush_all()
        response = self.url_open('/html_editor/shape/illustration/%s' % attachment.id)
        self.assertEqual(response.status_code, 404)

    def test_unknown_id_is_not_a_500(self):
        response = self.url_open('/html_editor/shape/illustration/999999999')
        self.assertEqual(response.status_code, 404)


@odoo.tests.tagged('-at_install', 'post_install')
class TestBusBroadcastFieldValidation(HttpCase):
    def test_unknown_field_is_rejected(self):
        """An unknown field name used to skip the field-level access checks and
        still broadcast on a channel derived from it."""
        self.authenticate('admin', 'admin')
        partner = self.env['res.partner'].create({'name': 'broadcast probe'})
        self.env.flush_all()
        def broadcast(field_name):
            # jsonrpc serialises the raised BadRequest into an error payload
            # with HTTP 200, so assert on the payload rather than the status.
            return self.url_open(
                '/html_editor/bus_broadcast',
                headers={'Content-Type': 'application/json'},
                data=json_safe.dumps({'params': {
                    'model_name': 'res.partner',
                    'field_name': field_name,
                    'res_id': partner.id,
                    'bus_data': {},
                }}),
            ).json()

        self.assertIn('error', broadcast('no_such_field_here'))
        # a real field on the same record must still be accepted
        self.assertNotIn('error', broadcast('comment'))
