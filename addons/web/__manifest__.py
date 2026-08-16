{
    "name": "Web",
    "version": "2.0",
    "category": "Hidden",
    "description": """
Odoo Web core module.
========================

This module provides the core of the Odoo Web Client.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "base",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/web_security.xml",
        "views/webclient_templates.xml",
        "views/report_templates.xml",
        "views/base_document_layout_views.xml",
        "views/partner_view.xml",
        "views/speedscope_template.xml",
        "views/memory_template.xml",
        "views/speedscope_config_wizard.xml",
        "views/neutralize_views.xml",
        "views/ir_ui_view_views.xml",
        "views/res_config_settings_views.xml",
        "views/res_users_views.xml",
        "views/web_cwv_metric_views.xml",
        "views/web_js_error_views.xml",
        "data/ir_attachment.xml",
        "data/report_theme.xml",
        "data/report_layout.xml",
        "data/web_cwv_metric_data.xml",
        "data/web_js_error_data.xml",
        "views/web_menus.xml",
    ],
    "assets": {
        "web.assets_emoji": [
            "web/static/src/components/emoji_picker/emoji_data.js",
        ],
        "web.assets_backend": [
            (
                "include",
                "web._assets_helpers",
            ),
            (
                "include",
                "web._assets_backend_helpers",
            ),
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            "web/static/lib/bootstrap/scss/_variables-dark.scss",
            "web/static/lib/bootstrap/scss/_maps.scss",
            (
                "include",
                "web._assets_bootstrap_backend",
            ),
            "web/static/src/scss/tokens.scss",
            "web/static/src/scss/scheme_rules.scss",
            (
                "include",
                "web._assets_core",
            ),
            "web/static/src/scss/fonts.scss",
            "web/static/src/libs/fontawesome7/css/fontawesome.css",
            "web/static/src/libs/fontawesome7/css/solid.css",
            "web/static/src/libs/fontawesome7/css/regular.css",
            "web/static/src/libs/fontawesome7/css/brands.css",
            "web/static/src/libs/fontawesome7/css/v4-shims.css",
            "web/static/lib/odoo_ui_icons/*",
            "web/static/src/webclient/navbar/navbar.scss",
            "web/static/src/scss/animation.scss",
            "web/static/src/scss/rtl_icon_flip.scss",
            "web/static/src/scss/mimetypes.scss",
            "web/static/src/scss/ui.scss",
            "web/static/src/fields/translation_dialog.scss",
            # Bootstrap's JS is deliberately absent from the backend. Nothing in
            # the web client reaches it: dropdowns, dialogs, popovers, tooltips,
            # collapses, offcanvases and carousels are served by
            # `web/static/src/ui` and `components/dropdown`, and arch written
            # against the data-api is rewritten by `ViewCompiler`. It is still
            # shipped to the frontend, where website content depends on it.
            "base/static/src/css/modules.css",
            "web/static/src/model/**/*",
            "web/static/src/search/**/*",
            "web/static/src/webclient/icons.scss",
            "web/static/src/fields/**/*",
            "web/static/src/views/**/*",
            "web/static/src/webclient/**/*",
            (
                "remove",
                "web/static/src/webclient/clickbot/clickbot.js",
            ),
            (
                "remove",
                "web/static/src/views/form/button_box/*.scss",
            ),
            (
                "remove",
                "web/static/src/webclient/actions/reports/**/*",
            ),
            "web/static/src/webclient/actions/reports/*.js",
            "web/static/src/webclient/actions/reports/*.xml",
            "web/static/src/scss/ace.scss",
            "web/static/src/scss/base_document_layout.scss",
            "base/static/src/scss/res_partner.scss",
            "base/static/src/scss/res_users.scss",
            "web/static/src/views/form/button_box/*.scss",
            (
                "remove",
                "web/static/src/**/*.dark.scss",
            ),
        ],
        "web.assets_web": [
            (
                "include",
                "web.assets_backend",
            ),
            "web/static/src/boot/start.js",
            "web/static/src/boot/main.js",
        ],
        "web.assets_frontend_minimal": [
            "web/static/src/session.js",
            "web/static/src/core/browser/cookie.js",
            "web/static/src/core/utils/dom/ui.js",
            "web/static/src/public/minimal_dom.js",
            "web/static/src/public/lazyloader.js",
        ],
        "web.assets_frontend": [
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
            (
                "include",
                "web._assets_bootstrap_frontend",
            ),
            "web/static/src/scss/tokens.scss",
            "web/static/src/scss/fonts.scss",
            "web/static/src/libs/fontawesome7/css/fontawesome.css",
            "web/static/src/libs/fontawesome7/css/solid.css",
            "web/static/src/libs/fontawesome7/css/regular.css",
            "web/static/src/libs/fontawesome7/css/brands.css",
            "web/static/src/libs/fontawesome7/css/v4-shims.css",
            "web/static/lib/odoo_ui_icons/*",
            "web/static/src/webclient/navbar/navbar.scss",
            "web/static/src/scss/animation.scss",
            "web/static/src/scss/base_frontend.scss",
            "web/static/src/scss/rtl_icon_flip.scss",
            "web/static/src/scss/mimetypes.scss",
            "web/static/src/scss/ui.scss",
            "web/static/src/fields/translation_dialog.scss",
            "web/static/src/fields/media/signature/signature_field.scss",
            (
                "include",
                "web.assets_frontend_minimal",
            ),
            "web/static/src/libs/popper_compat.js",
            "web/static/src/libs/bootstrap.js",
            "web/static/src/env.js",
            "web/static/src/ui/**/*",
            (
                "remove",
                "web/static/src/ui/commands/**/*",
            ),
            "web/static/src/ui/commands/default_providers.js",
            "web/static/src/ui/commands/command_palette.js",
            "web/static/src/components/**/*",
            "web/static/src/core/**/*",
            # The debug menu moved from `services/debug/` to `webclient/debug/`,
            # and `webclient/**` is not globbed here — so what used to arrive
            # via `services/**` has to be named. Listed file by file rather than
            # `webclient/debug/**`, because the set is the point: the frontend
            # gets the BASIC menu and its providers, never `debug_menu.js`,
            # which the old block removed by name for that reason.
            "web/static/src/webclient/debug/debug_menu_basic.js",
            "web/static/src/webclient/debug/debug_menu_items.js",
            "web/static/src/webclient/debug/debug_providers.js",
            "web/static/src/webclient/debug/debug_menu.scss",
            "web/static/src/webclient/debug/debug_menu.xml",
            "web/static/src/webclient/debug/debug_menu_items.xml",
            "web/static/src/webclient/install_scoped_app/install_scoped_app.js",
            "web/static/src/webclient/install_scoped_app/install_scoped_app.xml",
            (
                "remove",
                "web/static/src/components/emoji_picker/emoji_data.js",
            ),
            # There is no dark frontend bundle, so a `*.dark.scss` reaching
            # here is never the scheme answering: it compiles with the light
            # palette and overrides the light file it was written against.
            (
                "remove",
                "web/static/src/**/*.dark.scss",
            ),
            # frontend-only error handler: it swallows tracebacks for
            # non-internal users, and it says so itself by warning when
            # `session.is_frontend` and `isInternalUser` is missing. It lived in
            # `webclient/**`, which only `assets_backend` pulls in, so it was
            # dead code on the pages it exists for — every public-page failure
            # reached `defaultHandler` and raised a dialog at the visitor.
            "web/static/src/webclient/errors/visitor_error_handler.js",
            "web/static/src/public/**/*.js",
            "web/static/src/public/**/*.xml",
            (
                "remove",
                "web/static/src/public/database_manager.js",
            ),
        ],
        "web.assets_frontend_lazy": [
            (
                "include",
                "web.assets_frontend",
            ),
            (
                "remove",
                "web/static/src/session.js",
            ),
            (
                "remove",
                "web/static/src/core/browser/cookie.js",
            ),
            (
                "remove",
                "web/static/src/core/utils/dom/ui.js",
            ),
            (
                "remove",
                "web/static/src/public/minimal_dom.js",
            ),
            (
                "remove",
                "web/static/src/public/lazyloader.js",
            ),
        ],
        "web.report_assets_common": [
            "web/static/src/scss/functions.scss",
            "web/static/src/scss/utils.scss",
            (
                "include",
                "web._assets_primary_variables",
            ),
            (
                "include",
                "web._assets_secondary_variables",
            ),
            "web/static/src/webclient/actions/reports/bootstrap_overridden_report.scss",
            (
                "include",
                "web._assets_helpers",
            ),
            (
                "include",
                "web._assets_backend_helpers",
            ),
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            "web/static/lib/bootstrap/scss/_variables-dark.scss",
            "web/static/lib/bootstrap/scss/_maps.scss",
            (
                "include",
                "web._assets_bootstrap_backend",
            ),
            # Same slot it holds in `assets_backend`: after Bootstrap, whose
            # `$color-contrast-light`/`$white`/`$black`/`$min-contrast-ratio`
            # the schemes are built from. `bs_mixins_overrides.scss` arrives
            # with `_assets_backend_helpers` above and `html_editor.common.scss`
            # calls `o-cc-extras(..., o-light-scheme())` at the end of this
            # bundle, so its functions are invoked here whether or not it is
            # loaded -- and Sass emits an unknown function as literal CSS text
            # rather than failing, so leaving it out did not raise "undefined
            # function": it handed `button-variant()` the unevaluated call and
            # broke every report with "is not a color". `scheme_rules.scss`
            # deliberately stays out; its dark half is screen-only.
            "web/static/src/scss/tokens.scss",
            (
                "remove",
                "web/static/src/scss/utilities_custom_backend.scss",
            ),
            (
                "remove",
                "web/static/src/scss/bootstrap_review_backend.scss",
            ),
            (
                "after",
                "web/static/src/scss/utilities_custom.scss",
                "web/static/src/webclient/actions/reports/utilities_custom_report.scss",
            ),
            "web/static/src/libs/popper_compat.js",
            "web/static/src/libs/bootstrap.js",
            "base/static/src/css/description.css",
            "web/static/src/libs/fontawesome7/css/fontawesome.css",
            "web/static/src/libs/fontawesome7/css/solid.css",
            "web/static/src/libs/fontawesome7/css/regular.css",
            "web/static/src/libs/fontawesome7/css/brands.css",
            "web/static/src/libs/fontawesome7/css/v4-shims.css",
            "web/static/src/scss/rtl_icon_flip.scss",
            "web/static/lib/odoo_ui_icons/*",
            "web/static/fonts/fonts.scss",
            "web/static/src/webclient/actions/reports/bootstrap_review_report.scss",
            "web/static/src/webclient/actions/reports/report.scss",
            "web/static/src/webclient/actions/reports/report_tables.scss",
            "web/static/src/webclient/actions/reports/layout_assets/layout_*.scss",
            # No file behind it: `web.asset_styles_company_report` is an
            # ir.attachment that res.company regenerates, carrying each
            # company's `.o_company_N_layout` brand and report.theme tokens.
            "web/static/asset_styles_company_report.scss",
        ],
        "web.report_assets_pdf": [
            "web/static/src/webclient/actions/reports/reset.min.css",
            "web/static/src/webclient/actions/reports/report_paged_media.css",
            "web/static/src/webclient/actions/reports/report_pdf_layout.css",
        ],
        "web.ace_lib": [
            "web/static/lib/ace/ace.js",
            "web/static/lib/ace/mode-javascript.js",
            "web/static/lib/ace/mode-xml.js",
            "web/static/lib/ace/mode-qweb.js",
            "web/static/lib/ace/mode-python.js",
            "web/static/lib/ace/mode-scss.js",
            "web/static/lib/ace/mode-json.js",
            "web/static/lib/ace/theme-monokai.js",
        ],
        "web.assets_web_print": [
            "web/static/src/scss/functions.scss",
            "web/static/src/scss/primary_variables_print.scss",
            "web/static/src/**/*.print_variables.scss",
            (
                "include",
                "web.assets_backend",
            ),
        ],
        # Dark-mode variable layer. Every dark bundle includes it, and it is
        # walked once: the anchors below place each `*.dark.scss` immediately
        # ahead of the light file it answers, so `!default` resolves in favour
        # of dark. Themes contribute their own anchors to this same bundle and
        # land ahead of web's, which is why a theme must answer in dark every
        # variable it overrides in light.
        "web._dark_mode_variables": [
            # Ahead of the primitives, therefore ahead of every palette: a
            # theme reads the inverted ramp rather than answering it.
            (
                "before",
                "web/static/src/scss/primitives.scss",
                "web/static/src/scss/primitives.dark.scss",
            ),
            (
                "before",
                "web/static/src/scss/primary_variables.scss",
                "web/static/src/scss/primary_variables.dark.scss",
            ),
        ],
        "web.assets_web_dark": [
            (
                "include",
                "web.assets_web",
            ),
            (
                "include",
                "web._dark_mode_variables",
            ),
            (
                "after",
                "web/static/lib/bootstrap/scss/_functions.scss",
                "web/static/src/scss/bs_functions_overridden.dark.scss",
            ),
            "web/static/src/**/*.dark.scss",
        ],
        "web.assets_backend_dark": [
            (
                "include",
                "web._assets_helpers",
            ),
            (
                "include",
                "web._assets_backend_helpers",
            ),
            (
                "include",
                "web._dark_mode_variables",
            ),
            (
                "after",
                "web/static/lib/bootstrap/scss/_functions.scss",
                "web/static/src/scss/bs_functions_overridden.dark.scss",
            ),
            "web/static/src/**/*.dark.scss",
        ],
        "web._assets_core": [
            "web/static/src/session.js",
            "web/static/src/env.js",
            "web/static/src/ui/**/*",
            "web/static/src/components/**/*",
            "web/static/src/core/**/*",
            (
                "remove",
                "web/static/src/components/emoji_picker/emoji_data.js",
            ),
            # Every consumer of this fragment is a light bundle -- backend,
            # frontend, the PoS apps, the public sign page -- and the dark
            # bundles take the whole tree by glob anyway. Excluding here means
            # a new component's dark skin cannot leak into a light bundle just
            # because that bundle globs this directory.
            (
                "remove",
                "web/static/src/**/*.dark.scss",
            ),
        ],
        "web._assets_primary_variables": [
            # Before the primitives, and in every bundle rather than only the
            # dark ones: `tokens.scss` publishes both schemes, so the dark
            # values have to be resolvable at light-compile time.
            "web/static/src/scss/palette_dark.scss",
            # First, so every palette downstream — themes included, since they
            # anchor before primary_variables.scss — reads one definition of
            # the raw values instead of restating them to be able to use them.
            "web/static/src/scss/primitives.scss",
            "web/static/src/scss/primary_variables.scss",
            "web/static/src/**/*.variables.scss",
        ],
        "web._assets_secondary_variables": [
            "web/static/src/scss/secondary_variables.scss",
        ],
        "web._assets_helpers": [
            "web/static/lib/bootstrap/scss/_functions.scss",
            "web/static/lib/bootstrap/scss/_mixins.scss",
            "web/static/src/scss/functions.scss",
            "web/static/src/scss/mixins_forwardport.scss",
            "web/static/src/scss/bs_mixins_overrides.scss",
            "web/static/src/scss/utils.scss",
            (
                "include",
                "web._assets_primary_variables",
            ),
            (
                "include",
                "web._assets_secondary_variables",
            ),
        ],
        "web._assets_bootstrap": [
            "web/static/src/scss/import_bootstrap.scss",
            "web/static/src/scss/utilities_custom.scss",
            "web/static/lib/bootstrap/scss/utilities/_api.scss",
            "web/static/src/scss/bootstrap_review.scss",
        ],
        "web._assets_bootstrap_backend": [
            (
                "include",
                "web._assets_bootstrap",
            ),
            (
                "after",
                "web/static/src/scss/utilities_custom.scss",
                "web/static/src/scss/utilities_custom_backend.scss",
            ),
            "web/static/src/scss/bootstrap_review_backend.scss",
        ],
        "web._assets_bootstrap_frontend": [
            (
                "include",
                "web._assets_bootstrap",
            ),
            "web/static/src/scss/bootstrap_review_frontend.scss",
        ],
        "web._assets_backend_helpers": [
            "web/static/src/scss/bootstrap_overridden.scss",
            "web/static/src/scss/bs_mixins_overrides_backend.scss",
        ],
        "web._assets_frontend_helpers": [
            "web/static/src/scss/bootstrap_overridden_frontend.scss",
        ],
        "web.assets_tests": [
            "web/static/tests/helpers/cleanup.js",
            "web/static/tests/helpers/utils.js",
            "web/static/tests/utils.js",
            "web/static/tests/tours/**/*",
        ],
        "web.assets_unit_tests_setup": [
            # Their suites import them directly, and the backend bundle no
            # longer carries them — `website`, which does, is not installed in
            # a web-only test database.
            "web/static/src/libs/popper_compat.js",
            "web/static/src/libs/bootstrap.js",
            "web/static/lib/hoot/**/*",
            "web/static/lib/hoot-dom/**/*",
            (
                "remove",
                "web/static/lib/hoot/ui/hoot_style.css",
            ),
            (
                "remove",
                "web/static/lib/hoot/tests/**/*",
            ),
            (
                "include",
                "web.assets_backend",
            ),
            "web/static/src/public/minimal_dom.js",
            "web/static/src/public/lazyloader.js",
            "web/static/src/public/**/*.js",
            "web/static/src/public/**/*.xml",
            "web/static/tests/public/**/*.xml",
            (
                "remove",
                "web/static/src/public/database_manager.js",
            ),
            (
                "remove",
                "web/static/src/public/public_boot_instance.js",
            ),
            (
                "remove",
                "web/static/src/public/error_notifications.js",
            ),
            "web/static/src/webclient/clickbot/clickbot.js",
        ],
        "web.assets_unit_tests_setup_ui": [
            "web/static/lib/diff_match_patch/diff_match_patch.js",
            "web/static/lib/prismjs/prism.js",
        ],
        "web.assets_unit_tests": [
            "web/static/tests/**/*",
            (
                "remove",
                "web/static/tests/tours/**/*",
            ),
            (
                "remove",
                "web/static/tests/utils.js",
            ),
        ],
        "web.assets_clickbot": [
            "web/static/src/webclient/clickbot/clickbot.js",
        ],
    },
    "esm": {
        "bundles": [
            "web.assets_web",
            "web.assets_web_dark",
            "web.assets_web_print",
            "web.assets_frontend",
            "web.assets_frontend_lazy",
            "web.assets_frontend_minimal",
            "web.assets_inside_builder_iframe",
            "web.report_assets_common",
            "web.report_assets_pdf",
            "web.assets_tests",
            "web.assets_unit_tests",
            "web.assets_unit_tests_setup",
            "web.assets_clickbot",
            "web.assets_emoji",
        ],
        "dynamic_children": {
            "web.assets_web": [
                "web.assets_clickbot",
                "web.assets_emoji",
            ],
        },
        "external_libs": {
            "@odoo/owl": "/web/static/lib/owl/owl.es.js",
            "@odoo/hoot": "/web/static/lib/hoot/hoot.js",
            "@odoo/hoot-dom": "/web/static/lib/hoot-dom/hoot-dom.js",
            "@odoo/hoot-mock": "/web/static/lib/hoot/hoot-mock.js",
            "@odoo/hoot-dom-helpers-dom": "/web/static/lib/hoot-dom/helpers/dom.js",
            "@odoo/hoot-dom-helpers-events": (
                "/web/static/lib/hoot-dom/helpers/events.js"
            ),
            "@odoo/hoot-dom-helpers-time": "/web/static/lib/hoot-dom/helpers/time.js",
            "@odoo/hoot-dom-utils": "/web/static/lib/hoot-dom/hoot_dom_utils.js",
            "@popperjs/core": "/web/static/lib/popper_compat/popper_compat.esm.js",
            "luxon": "/web/static/lib/luxon/luxon.js",
            "dompurify": "/web/static/lib/dompurify/purify.es.js",
            "signature_pad": "/web/static/lib/signature_pad/signature_pad.js",
            "zxing-library": "/web/static/lib/zxing-library/zxing-library.js",
            "pdfjs-dist": "/web/static/lib/pdfjs/build/pdf.js",
            "chart.js": "/web/static/lib/Chart/Chart.js",
            "chart.js/helpers": "/web/static/lib/Chart/helpers.js",
            "chartjs-adapter-luxon": (
                "/web/static/lib/chartjs-adapter-luxon/chartjs-adapter-luxon.js"
            ),
            "@fullcalendar/core": "/web/static/lib/fullcalendar/fullcalendar.esm.js",
            "@fullcalendar/core/locales-all": (
                "/web/static/lib/fullcalendar/locales-all.esm.js"
            ),
        },
        "import_map_includes": {
            "web.assets_unit_tests_setup": [
                "web.assets_unit_tests",
            ],
        },
        "secondary_import_map_includes": {
            "web.assets_web": [
                "web.assets_tests",
            ],
            "web.assets_frontend": [
                "web.assets_tests",
            ],
            "web.assets_frontend_lazy": [
                "web.assets_tests",
            ],
        },
    },
    "auto_install": True,
    "bootstrap": True,
}
