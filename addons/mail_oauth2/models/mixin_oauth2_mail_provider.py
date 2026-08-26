import json
import logging
import time
from urllib.parse import urlencode as url_encode

import requests

from odoo import _, fields, models, release
from odoo.exceptions import AccessError, UserError
from odoo.libs.web import urljoin as url_join
from odoo.tools import email_normalize, hmac

from odoo.addons.mail_oauth2.tools import get_iap_error_message

OAUTH2_TOKEN_REQUEST_TIMEOUT = 5

# seconds removed from end-of-validity datetime to take into account the time
# needed to renew the token and open the new smtp session
OAUTH2_TOKEN_VALIDITY_THRESHOLD = OAUTH2_TOKEN_REQUEST_TIMEOUT + 5

_logger = logging.getLogger(__name__)


class MixinOauth2MailProvider(models.AbstractModel):
    _name = 'mixin.oauth2.mail.provider'

    _description = 'OAuth2 Mail Provider Mixin'

    active = fields.Boolean(default=True)

    def _oauth2_credentials(self, provider):
        Config = self.env['ir.config_parameter'].sudo()
        return (
            Config.get_param(provider.field('client_id')),
            Config.get_param(provider.field('client_secret')),
        )

    def _oauth2_redirect_uri(self, provider):
        return url_join(self.get_base_url(), f'/{provider.route}/confirm')

    def _oauth2_iap_endpoint(self, provider):
        return self.env['ir.config_parameter'].sudo().get_param(
            provider.iap_endpoint_param,
            provider.iap_endpoint_default,
        )

    def _oauth2_compute_uri(self, provider):
        fname = provider.field('uri')
        client_id, client_secret = self._oauth2_credentials(provider)
        is_configured = client_id and client_secret
        authorize_url = provider.resolve(provider.authorize_url, self)
        scope = provider.resolve(provider.scope, self)

        for record in self:
            if not is_configured:
                record[fname] = False
                continue

            record[fname] = '%s?%s' % (authorize_url, url_encode({
                'client_id': client_id,
                'response_type': 'code',
                'redirect_uri': record._oauth2_redirect_uri(provider),
                'scope': scope,
                **provider.authorize_extra_params,
                # an unsaved record's id is a NewId: falsy, and json cannot
                # serialise it. Send no id rather than raising in the compute.
                'state': json.dumps({
                    'model': record._name,
                    'id': record.id or False,
                    'csrf_token': record._oauth2_csrf_token(provider) if record.id else False,
                }),
            }))

    def _oauth2_open_uri(self, provider):
        """Return the action opening the provider's consent screen.

        An action rather than a bare URL so the form is saved first: the record
        must exist in DB for its id to travel in the callback state.
        """
        self.ensure_one()

        if not self.env.is_admin():
            raise AccessError(_('Only the administrator can link a mail server to %s.', provider.label))

        if not email_normalize(self[self._email_field]):
            raise UserError(_('Please enter a valid email address.'))

        client_id, client_secret = self._oauth2_credentials(provider)
        if client_id and client_secret:
            uri = self[provider.field('uri')]
        else:
            uri = self._oauth2_iap_authorize_uri(provider)

        if not uri:
            raise UserError(_('Please configure your %s credentials.', provider.label))

        return {
            'type': 'ir.actions.act_url',
            'url': uri,
            'target': 'self',
        }

    def _oauth2_iap_authorize_uri(self, provider):
        """Ask IAP for the URL redirecting the user to the provider's login page."""
        if release.version_info[-1] != 'e':
            raise UserError(_('Please configure your %s credentials.', provider.label))

        db_uuid = self.env['ir.config_parameter'].sudo().get_param('database.uuid')
        callback_params = url_encode({
            'model': self._name,
            'rec_id': self.id,
            'csrf_token': self._oauth2_csrf_token(provider),
        })
        callback_url = url_join(self.get_base_url(), f'/{provider.route}/iap_confirm?{callback_params}')

        try:
            response = requests.get(
                url_join(self._oauth2_iap_endpoint(provider), f'/api/mail_oauth/1/{provider.iap_service}'),
                params={'db_uuid': db_uuid, 'callback_url': callback_url},
                timeout=OAUTH2_TOKEN_REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            _logger.error('Can not contact IAP: %s.', e)
            raise UserError(_('Oops, we could not authenticate you. Please try again later.')) from e

        response = response.json()
        if 'error' in response:
            self._raise_iap_error(response['error'])

        return response['url']

    def _oauth2_get_refresh_token(self, provider, authorization_code):
        """Exchange the authorization code for the first refresh and access tokens.

        :return: refresh_token, access_token, access_token_expiration
        """
        response = self._oauth2_get_token(provider, 'authorization_code', code=authorization_code)
        return (
            response['refresh_token'],
            response['access_token'],
            int(time.time()) + int(response['expires_in']),
        )

    def _oauth2_get_token(self, provider, grant_type, **values):
        """Request a token from the provider and return its JSON payload.

        :param grant_type: the OAuth grant to use (authorization_code or refresh_token)
        :param values: additional parameters given to the token endpoint
        """
        client_id, client_secret = self._oauth2_credentials(provider)
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': grant_type,
            'redirect_uri': self._oauth2_redirect_uri(provider),
            **values,
        }
        if provider.token_sends_scope:
            data['scope'] = provider.resolve(provider.scope, self)

        response = requests.post(
            provider.resolve(provider.token_url, self),
            data=data,
            timeout=OAUTH2_TOKEN_REQUEST_TIMEOUT,
        )

        if not response.ok:
            raise UserError(self._oauth2_token_error(provider, response))

        return response.json()

    def _oauth2_token_error(self, provider, response):
        if not provider.token_error_detail:
            return _('An error occurred when fetching the access token.')
        try:
            detail = response.json()['error_description']
        except Exception:
            detail = _('Unknown error.')
        return _('An error occurred when fetching the access token. %s', detail)

    def _oauth2_get_access_token_iap(self, provider, refresh_token):
        """Fetch the access token through IAP, which relays it to the provider.

        :return: the payload answered by IAP, relayed as-is. It is positional,
            and its arity matches what the provider's own refresh returns.
        """
        db_uuid = self.env['ir.config_parameter'].sudo().get_param('database.uuid')

        response = requests.get(
            url_join(self._oauth2_iap_endpoint(provider), f'/api/mail_oauth/1/{provider.iap_service}_access_token'),
            params={'refresh_token': refresh_token, 'db_uuid': db_uuid},
            timeout=OAUTH2_TOKEN_REQUEST_TIMEOUT,
        )

        if not response.ok:
            _logger.error('Can not contact IAP: %s.', response.text)
            raise UserError(_('Oops, we could not authenticate you. Please try again later.'))

        response = response.json()
        if 'error' in response:
            self._raise_iap_error(response['error'])

        return response

    def _raise_iap_error(self, error):
        raise UserError(get_iap_error_message(self.env, error))

    def _oauth2_generate_string(self, provider, login, renew):
        """Return the SASL argument for the XOAUTH2 mechanism.

        :param renew: called to refresh and store the token when it is stale.
            The providers disagree on what a refresh answers -- Google returns
            an access token alone, Microsoft rotates the refresh token and adds
            an id token -- so persisting it stays with them.
        """
        self.ensure_one()
        now_timestamp = int(time.time())
        expiration = self[provider.field('access_token_expiration')]

        if (not self[provider.field('access_token')] or not expiration
                or expiration - OAUTH2_TOKEN_VALIDITY_THRESHOLD < now_timestamp):
            renew()
            _logger.info(
                '%s: fetch new access token. It expires in %i minutes', provider.label,
                (self[provider.field('access_token_expiration')] - now_timestamp) // 60)
        else:
            _logger.info(
                '%s: reuse existing access token. It expires in %i minutes', provider.label,
                (expiration - now_timestamp) // 60)

        return 'user=%s\1auth=Bearer %s\1\1' % (login, self[provider.field('access_token')])

    def _oauth2_csrf_token(self, provider):
        """Generate the CSRF token the OAuth callback verifies.

        This prevents a malicious person from making an admin user disconnect
        the mail servers.
        """
        self.ensure_one()
        _logger.info('%s: generate CSRF token for %s #%i', provider.label, self._name, self.id)
        return hmac(
            env=self.env(su=True),
            scope=provider.csrf_scope,
            message=(self._name, self.id),
        )
