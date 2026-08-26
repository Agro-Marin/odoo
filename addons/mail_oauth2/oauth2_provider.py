import dataclasses
from collections.abc import Callable


@dataclasses.dataclass(frozen=True)
class Oauth2MailProvider:
    """Everything ``mixin.oauth2.mail.provider`` needs to run one provider's flow.

    A concrete provider mixin holds one of these and passes it to every shared
    method. It is never resolved through the MRO: ``ir.mail_server`` and
    ``fetchmail.server`` each carry *both* provider mixins, so a class attribute
    would let one provider's prefix answer for the other.

    ``authorize_url``, ``token_url`` and ``scope`` accept a callable taking the
    recordset, for the providers whose endpoint or scope is only known at
    runtime.
    """

    prefix: str
    label: str
    route: str
    csrf_scope: str
    iap_service: str
    iap_endpoint_param: str
    iap_endpoint_default: str
    authorize_url: str | Callable
    token_url: str | Callable
    scope: str | Callable
    authorize_extra_params: dict = dataclasses.field(default_factory=dict)
    token_sends_scope: bool = False
    token_error_detail: bool = False

    def field(self, suffix):
        return f'{self.prefix}_{suffix}'

    def resolve(self, value, records):
        return value(records) if callable(value) else value
