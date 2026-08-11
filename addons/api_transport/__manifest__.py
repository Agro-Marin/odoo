{
    "name": "API Transport",
    "version": "19.0.1.3.0",
    "category": "Technical",
    "sequence": 5,
    "summary": "Unified bidirectional API communication framework for inbound and outbound integrations",
    "description": """
API Transport
=============

Unified transport for all API communication - both inbound (receiving webhooks, IoT
data) and outbound (calling external APIs, external services).

Promoted from ``agromarin/api_communication`` into the core fork so that modules
in odoo/ and enterprise/ can depend on it; renamed to say what it is.

Key Features
------------

**Bidirectional Communication:**
* Inbound endpoints: Receive webhooks, IoT device data, external notifications
* Outbound services: Call REST APIs, payment gateways, external systems
* Unified event logging with direction tracking

**Security & Authentication:**
* Bearer Token authentication
* HMAC signature verification (SHA-256/SHA-512)
* OAuth 2.0 support for outbound services
* IP whitelisting for inbound endpoints
* Timestamp verification (replay attack prevention)

**Rate Limiting:**
* Token bucket algorithm (database-backed)
* Configurable per endpoint/service
* Multi-company isolation

**Resilience:**
* Automatic retry with exponential backoff
* Health monitoring for outbound services
* Async processing queue for inbound events
* Response caching for outbound calls

**Logging & Monitoring:**
* Unified event log with direction (inbound/outbound)
* Performance metrics and timing
* Error tracking and categorization
* Configurable retention policies

Technical
---------
* Session pooling for outbound connections
* Constant-time signature comparison (timing attack prevention)
* Field-level encryption for secrets (via base_credential_manager)
* Multi-company support with record rules
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "base_credential_manager",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/ir_config_parameter_data.xml",
        "data/ir_cron_data.xml",
        "views/api_event_log_views.xml",
        "views/api_endpoint_outbound.xml",
        "views/response_cache_views.xml",
        "views/api_transport_menu.xml",
    ],
    "demo": [
        "demo/comm_demo_data.xml",
    ],
    "application": True,
    "pre_init_hook": "pre_init_hook",
    "post_init_hook": "post_init_hook",
}
