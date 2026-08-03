{
    "name": "Documents",
    "summary": "Collect, organize and share documents.",
    "description": """
Store, organize and share files: a folder tree with per-document access rights,
share links, versioning, a trash and the Documents workspace.

`documents_enterprise` adds the sharing, operation and link-to-record wizards,
the onboarding tour, the digest KPIs and the Studio automation upsell.
    """,
    "category": "Productivity/Documents",
    "sequence": 80,
    # Continues the pre-split `documents` module, which shipped 1.5. Declaring
    # anything lower would be a downgrade on existing databases and would put
    # migrations/1.5/ permanently out of reach (see odoo/modules/migration.py).
    "version": "1.6",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/documents",
    "depends": [
        "mail",
        "portal",
        "attachment_indexation",
        # `add_documents_attachment` sets `ir.attachment.original_id` and calls
        # `_get_media_info`, both defined here. It reached them through mail's
        # own dependency, so the graph did not record that documents needs this
        # module -- and the day mail stops depending on it, an editor upload
        # fails on a field that no longer exists.
        "html_editor",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/mail_template_data.xml",
        "data/mail_activity_type_data.xml",
        "data/documents_tag_data.xml",
        "data/documents_document_data.xml",
        # folder has to exist
        "data/mail_alias_data.xml",
        "data/ir_config_parameter_data.xml",
        "data/ir_cron_data.xml",
        "views/res_config_settings_views.xml",
        "views/res_partner_views.xml",
        "views/documents_access_views.xml",
        "views/documents_document_views.xml",
        "views/documents_folder_views.xml",
        "views/documents_tag_views.xml",
        "views/mail_activity_views.xml",
        "views/mail_activity_plan_views.xml",
        "views/mail_alias_views.xml",
        # after the action files above, before the files referencing its menus
        "views/documents_menu_views.xml",
        "views/documents_access_log_views.xml",
        "views/documents_templates_portal.xml",
        "views/documents_templates_share.xml",
        "views/documents_templates_thumbnails.xml",
        "views/ir_actions_views.xml",
        "views/mail_compose_message_views.xml",
        "views/mail_scheduled_message_views.xml",
        "wizard/documents_request_wizard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "documents/static/src/scss/documents_views.scss",
            "documents/static/src/scss/documents_kanban_view.scss",
            "documents/static/src/attachments/**/*",
            "documents/static/src/core/**/*",
            "documents/static/src/js/**/*",
            "documents/static/src/mail/**/*",
            "documents/static/src/owl/**/*",
            "documents/static/src/utils.js",
            "documents/static/src/views/**/*",
            "documents/static/src/webclient/webclient.js",
            (
                "after",
                "web/static/src/components/errors/error_dialogs.xml",
                "documents/static/src/web/error_dialog/error_dialog_patch.xml",
            ),
            "documents/static/src/web/**/*",
            "documents/static/src/components/**/*",
            "documents/static/src/editor/**/*",
        ],
        "web._assets_primary_variables": [
            "documents/static/src/scss/documents.variables.scss",
        ],
        "web.assets_tests": [
            "documents/static/tests/tours/*",
        ],
        "web.assets_unit_tests": [
            "documents/static/tests/**/*",
        ],
        # The public share page and the portal webclient are served by this
        # module's controllers, so their bundles live here too.
        "documents.public_page_assets": [
            ("include", "web._assets_helpers"),
            ("include", "web._assets_backend_helpers"),
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            "web/static/lib/bootstrap/scss/_variables-dark.scss",
            "web/static/lib/bootstrap/scss/_maps.scss",
            ("include", "web._assets_bootstrap_backend"),
            "documents/static/src/scss/documents_public_pages.scss",
        ],
        "documents.webclient": [
            ("include", "web.assets_backend"),
            # documents webclient overrides
            "documents/static/src/portal_webclient/**/*",
            "web/static/src/boot/start.js",
        ],
    },
    "esm": {
        # ESM/esbuild bundle taxonomy — aggregated and validated by
        # odoo.libs.esm_registry (see its docstring for the schema).
        "bundles": [
            "documents.public_page_assets",
            "documents.webclient",
        ],
        # The documents portal page renders web.assets_tests after this app
        # bundle in test mode; declare it a secondary so the served import map
        # carries the singleton-preserving bridges (browser/registry/…) the test
        # bundle externalises. See web.assets_tests / the 2026-07 split note.
        # (The public share page renders web.assets_frontend first, already a
        # declared parent, so it needs no entry here.)
        "secondary_import_map_includes": {
            "documents.webclient": ["web.assets_tests"],
        },
    },
    "demo": [
        "demo/documents_document_demo.xml",
    ],
    "application": True,
    "license": "LGPL-3",
}
