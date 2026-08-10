"""Webhook / inbound-request authentication helpers — re-export shim.

The canonical implementation lives in
``odoo.addons.base_credential_manager.tools.authentication`` (it was promoted
to the core fork together with the credential vault so ``base_automation``
webhooks could use it). This module used to carry a near-identical copy that
had already started to drift; it is now a pure re-export so the two can never
diverge again.

Backward compatibility:

* The public API (``verify_signature``, ``verify_timestamp``,
  ``verify_hmac_signature``, ``verify_bearer_token``) is unchanged.
* The ``timestamp_future_tolerance`` and ``allow_none_signature`` system
  parameters are still honored under this module's own prefix
  (``api_transport.*``) and, for databases that predate two renames, under the
  historical ``api_communication.*`` one. The canonical
  ``base_credential_manager.*`` key wins over both; see
  ``_get_param_with_legacy`` there for the order.
* Log records are now emitted by the canonical module's logger
  (``odoo.addons.base_credential_manager.tools.authentication``); use that
  name in ``mute_logger``.
"""

from odoo.addons.base_credential_manager.tools.authentication import (
    _handle_none_signature,
    _verify_custom,
    verify_bearer_token,
    verify_hmac_signature,
    verify_signature,
    verify_timestamp,
)

__all__ = [
    "_handle_none_signature",
    "_verify_custom",
    "verify_bearer_token",
    "verify_hmac_signature",
    "verify_signature",
    "verify_timestamp",
]
