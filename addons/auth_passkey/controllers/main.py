from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.home import CREDENTIAL_PARAMS

if 'webauthn_response' not in CREDENTIAL_PARAMS:
    CREDENTIAL_PARAMS.append('webauthn_response')


class WebauthnController(http.Controller):
    @http.route(['/auth/passkey/start-auth'], type='jsonrpc', auth='public')
    def json_start_authentication(self):
        return request.env['auth.passkey.key']._start_auth()
