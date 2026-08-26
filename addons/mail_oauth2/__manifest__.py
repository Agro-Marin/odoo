{
    "name": "Mail OAuth2",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Foundation mixin for OAuth2-authenticated mail servers",
    "description": """
Mail OAuth2
============

Provides ``mixin.oauth2.mail.provider``, the abstract authorization-code flow
shared by every OAuth2 mail provider: the authorization URI, the IAP fallback,
the token exchange and refresh, the CSRF token, and the XOAUTH2 SASL string.

A provider supplies its endpoints and its identifiers through a handful of
class attributes and hooks, and declares its own credential fields under its
own prefix. It does not restate the flow.
    """,
    "author": "Odoo Community",
    "license": "LGPL-3",
    "depends": [
        "mail",
    ],
    "auto_install": True,
}
