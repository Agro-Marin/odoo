{
    "name": "Base Credential Manager",
    "version": "19.0.1.0.4",
    "category": "Technical",
    "sequence": 5,
    "summary": "Foundation module for secure credential management across all external integrations",
    "description": """
Base Credential Manager
=======================

Foundation module providing secure credential management infrastructure for ALL external service integrations.

Key Features
------------
**Universal Credential Storage:**
* Encrypted credential storage using Fernet (AES-128)
* Environment variable key management (ODOO_API_ENCRYPTION_KEY)
* Support for multiple credential types (API Key, OAuth, AWS IAM, etc.)
* Credential validation framework

**Multi-Tenancy:**
* Company-scoped credentials with automatic isolation
* Record rules enforce company boundaries
* Cost segregation per company

**Performance:**
* LRU session caching with TTL
* Thread-safe cache operations
* Connection pooling support
* Automatic cache invalidation

**Security:**
* Field-level encryption (Fernet symmetric encryption)
* Encryption key stored in environment variable (NOT database)
* Audit logging for credential access
* Health monitoring and validation

**Developer Experience:**
* Simple mixin pattern for credential models
* Pluggable validation framework
* Comprehensive error messages
* Full test coverage

Usage
-----
Other modules build on this module in two ways:

* Reference ``credential.credential`` records (or extend the model via
  ``_inherit``) to store their secrets encrypted — see ``api_communication``
  and ``api_gateway``.
* Import the shared primitives from ``tools/`` (authentication/signature
  verification, endpoint + credential rate limiters, session cache,
  connection manager) — see ``base_automation`` webhooks, ``telegram_bot``
  and ``remote``.

Requires the ``ODOO_API_ENCRYPTION_KEY`` environment variable (a Fernet key);
old keys stay readable through ``ODOO_API_ENCRYPTION_KEY_V<n>`` during
rotation.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "depends": ["base"],
    "data": [
        # Security (order matters!)
        "security/credential_security.xml",  # Groups and privileges first
        "security/ir.model.access.csv",  # Access rights second
        "security/ir_rule.xml",  # Record rules third
        # Data
        "data/credential_category_data.xml",  # Default categories
        "data/ir_cron.xml",  # Automated health checks and cleanup
        # Views (credential first - category references its action)
        "views/credential_credential_views.xml",
        "views/credential_category_views.xml",
        "views/credential_access_log_views.xml",
        "views/rate_limit_bucket_views.xml",
        "views/credential_menu.xml",
    ],
    "license": "LGPL-3",
}
