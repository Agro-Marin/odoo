{
    "name": "IM Bus",
    "version": "1.0",
    "category": "Hidden",
    "description": "Instant Messaging Bus allow you to send messages to users, in live.",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_backend": [
            "bus/static/src/*.js",
            "bus/static/src/debug/**/*",
            "bus/static/src/services/**/*.js",
            "bus/static/src/workers/*",
            ("remove", "bus/static/src/workers/bus_worker_script.js"),
        ],
        "web.assets_frontend": [
            "bus/static/src/*.js",
            "bus/static/src/services/**/*.js",
            ("remove", "bus/static/src/services/assets_watchdog_service.js"),
            ("remove", "bus/static/src/simple_notification_service.js"),
            "bus/static/src/workers/*",
            ("remove", "bus/static/src/workers/bus_worker_script.js"),
        ],
        # Unit test files
        "web.assets_unit_tests": [
            "bus/static/tests/**/*",
        ],
        "bus.websocket_worker_assets": [
            "bus/static/src/workers/*",
        ],
    },
    # The worker bundle is esbuild-compiled into ONE self-contained file (see
    # ir.qweb._get_websocket_worker_bundle_url): module workers booted from a
    # blob: URL (cross-origin prefork setup) cannot resolve relative imports.
    # standalone: workers have no import map and no `odoo` global, so the
    # page-context glue (owl external, odoo.loader registration) is skipped.
    "esm": {
        "bundles": ["bus.websocket_worker_assets"],
        "standalone_bundles": ["bus.websocket_worker_assets"],
    },
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "installable": True,
    "auto_install": True,
}
