import dataclasses
from collections.abc import Callable


@dataclasses.dataclass(frozen=True)
class Oauth2MailProvider:
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
        return f"{self.prefix}_{suffix}"

    def resolve(self, value, records):
        return value(records) if callable(value) else value
