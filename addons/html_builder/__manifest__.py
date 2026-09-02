{
    "name": "HTML Builder",
    "version": "0.1",
    "category": "Uncategorized",
    "summary": "Generic html builder",
    "description": """
    This addon contains a generic html builder application. It is designed to be
    used by the website builder and mass mailing editor.
    """,
    "author": "Odoo",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "mail",
    ],
    "assets": {
        "web._assets_primary_variables": [
            "html_builder/static/src/**/*.variables.scss",
        ],
        "html_builder.assets": [
            (
                "include",
                "web._assets_helpers",
            ),
            "html_editor/static/src/scss/bootstrap_overridden.scss",
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            "web/static/lib/bootstrap/scss/_variables-dark.scss",
            "web/static/lib/bootstrap/scss/_maps.scss",
            "web/static/fonts/fonts.scss",
            "html_builder/static/src/**/*",
            (
                "remove",
                "html_builder/static/src/**/*.edit.*",
            ),
        ],
        "web.assets_frontend": [
            "html_builder/static/src/scss/background.scss",
        ],
        "html_builder.assets_inside_builder_iframe": [
            (
                "include",
                "web._assets_helpers",
            ),
            "web/static/src/scss/bootstrap_overridden.scss",
            "html_builder/static/src/**/*.edit.*",
            "html_editor/static/src/main/chatgpt/chatgpt_plugin.scss",
            "html_editor/static/src/main/link/link.scss",
        ],
        "html_builder.iframe_add_dialog": [
            (
                "include",
                "web._assets_helpers",
            ),
            (
                "include",
                "web._assets_frontend_helpers",
            ),
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            "web/static/lib/bootstrap/scss/_variables-dark.scss",
            "web/static/lib/bootstrap/scss/_maps.scss",
            "html_builder/static/src/snippets/snippet_viewer.scss",
        ],
        "web.assets_unit_tests": [
            "html_builder/static/tests/**/*",
            (
                "include",
                "html_builder.assets",
            ),
        ],
    },
    "esm": {
        "bundles": [
            "html_builder.assets",
            "html_builder.assets_inside_builder_iframe",
        ],
    },
}
