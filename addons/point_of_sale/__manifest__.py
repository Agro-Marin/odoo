# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name": "Point of Sale",
    "version": "1.0.2",
    "category": "Sales/Point of Sale",
    "sequence": 40,
    "summary": "Handle checkouts and payments for shops and restaurants.",
    "depends": [
        "resource",
        "stock_account",
        "phone_validation",
        "partner_autocomplete",
        "iot_base",
        "google_address_autocomplete",
    ],
    "uninstall_hook": "uninstall_hook",
    "data": [
        "security/point_of_sale_security.xml",
        "security/ir.model.access.csv",
        "data/default_barcode_patterns.xml",
        "data/digest_data.xml",
        "data/pos_note_data.xml",
        "data/point_of_sale_tour.xml",
        "data/mail_template_data.xml",
        "data/ir_config_parameter_data.xml",
        "wizard/pos_details.xml",
        "wizard/pos_payment.xml",
        "wizard/pos_close_session_wizard.xml",
        "wizard/pos_daily_sales_reports.xml",
        "wizard/pos_confirmation_wizard.xml",
        "wizard/pos_make_invoice.xml",
        "views/pos_assets_index.xml",
        "views/point_of_sale_report.xml",
        "views/point_of_sale_view.xml",
        "views/pos_note_view.xml",
        "views/pos_order_view.xml",
        "views/pos_category_view.xml",
        "views/product_combo_views.xml",
        "views/product_view.xml",
        "views/account_journal_view.xml",
        "views/pos_payment_method_views.xml",
        "views/pos_payment_views.xml",
        "views/pos_config_view.xml",
        "views/pos_bill_view.xml",
        "views/pos_session_view.xml",
        "views/point_of_sale_sequence.xml",
        "data/point_of_sale_data.xml",
        "views/pos_order_report_view.xml",
        "views/digest_views.xml",
        "views/res_partner_view.xml",
        "views/report_userlabel.xml",
        "views/report_saledetails.xml",
        "views/pos_preset_view.xml",
        "views/point_of_sale_dashboard.xml",
        "views/report_invoice.xml",
        "views/pos_printer_view.xml",
        "views/pos_ticket_view.xml",
        "views/res_config_settings_views.xml",
        "views/customer_display_index.xml",
        "views/account_move_views.xml",
        "views/pos_session_sales_details.xml",
        "views/product_tag_views.xml",
        "views/stock_reference_views.xml",
    ],
    "demo": [
        "data/demo_data.xml",
    ],
    "installable": True,
    "application": True,
    "website": "https://www.odoo.com/app/point-of-sale-shop",
    "assets": {
        # In general, you DON'T NEED to declare new assets here, just put the
        # files in the proper directory. In rare cases, the order of scss files
        # matter and in that case you'll need to add it to the bundle in the
        # correct spot.
        #
        # Files in /static/src/backend will be loaded in the backend
        # Files in /static/src/app will be loaded in the PoS UI
        # Files in /static/tests/tours will be loaded in the backend in test mode
        # Files in /static/tests/unit will be loaded in the unit tests
        # web assets
        "web.assets_backend": [
            "point_of_sale/static/src/scss/pos_dashboard.scss",
            "point_of_sale/static/src/backend/tours/point_of_sale.js",
            "point_of_sale/static/src/backend/pos_kanban_view/*",
            "point_of_sale/static/src/backend/pos_payment_provider_cards/*",
            "point_of_sale/static/src/app/hooks/hooks.js",
            "point_of_sale/static/src/backend/many2many_placeholder_list_view/*",
            "point_of_sale/static/src/backend/test_epos/*",
            "point_of_sale/static/src/app/utils/init_lna.js",
        ],
        "web.assets_web_dark": [
        ],
        "web.assets_tests": [
            "barcodes/static/tests/legacy/helpers.js",
            "point_of_sale/static/tests/pos/tours/**/*",
            "point_of_sale/static/tests/generic_helpers/**/*",
            "point_of_sale/static/tests/customer_display/**/*",
            "point_of_sale/static/src/utils.js",
        ],
        "web.assets_unit_tests_setup": [
            ("include", "point_of_sale.assets_prod"),
            ("remove", "point_of_sale/static/src/app/main.js"),
            # Remove CSS files since we're not testing the UI with hoot in PoS
            # CSS files make html_editor tests fail
            ("remove", "point_of_sale/static/src/**/*.css"),
            # Adding error handler back since they are removed in the prod bundle
            "web/static/src/services/error_handlers.js",
            "web/static/src/ui/dialog/dialog.scss",
        ],
        "web.assets_unit_tests": [
            "point_of_sale/static/tests/unit/**/*",
        ],
        # PoS assets
        "point_of_sale.base_app": [
            ("include", "web._assets_helpers"),
            ("include", "web._assets_backend_helpers"),
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            "web/static/lib/bootstrap/scss/_variables-dark.scss",
            "web/static/lib/bootstrap/scss/_maps.scss",
            ("include", "web._assets_bootstrap_backend"),
            # web._assets_core carries the component stylesheets that read the
            # `--o-*` palette, so every bundle including it has to publish them
            # -- an unresolvable var() voids the whole declaration. Same slot as
            # in web.assets_backend: after Bootstrap, before the readers.
            "web/static/src/scss/tokens.scss",
            ("include", "web._assets_core"),
            ("remove", "web/static/src/core/browser/router.js"),
            ("remove", "web/static/src/services/debug/**/*"),
            "web/static/src/libs/fontawesome7/css/fontawesome.css",
            "web/static/src/libs/fontawesome7/css/solid.css",
            "web/static/src/libs/fontawesome7/css/regular.css",
            "web/static/src/libs/fontawesome7/css/brands.css",
            "web/static/src/core/formatters.js",
            "web/static/lib/odoo_ui_icons/*",
            "point_of_sale/static/src/utils.js",
            "bus/static/src/services/bus_service.js",
            "bus/static/src/services/worker_service.js",
            "bus/static/src/bus_parameters_service.js",
            "bus/static/src/legacy_multi_tab_service.js",
            "bus/static/src/multi_tab_service.js",
            "bus/static/src/workers/*",
            "iot_base/static/src/network_utils/*",
            "iot_base/static/src/device_controller.js",
        ],
        # Main PoS assets, they are loaded in the PoS UI
        "point_of_sale._assets_pos": [
            "web/static/src/scss/functions.scss",
            # JS boot
            # libs (should be loaded before framework)
            "point_of_sale/static/lib/**/*",
            ("include", "point_of_sale.base_app"),
            "web/static/src/components/colorlist/colorlist.scss",
            "web/static/src/webclient/webclient_layout.scss",
            "web/static/src/webclient/icons.scss",
            # scss variables and utilities
            "point_of_sale/static/src/scss/pos_variables_extra.scss",
            "web/static/src/scss/bootstrap_overridden.scss",
            "web/static/src/scss/rtl_icon_flip.scss",
            "web/static/fonts/fonts.scss",
            "web/static/src/scss/ui.scss",
            (
                "remove",
                "web/static/src/services/error_handlers.js",
            ),  # error handling in PoS is different from the webclient
            ("remove", "/web/static/src/ui/dialog/dialog.scss"),
            "web/static/src/services/currency.js",
            # barcode scanner
            "barcodes/static/src/barcode_service.js",
            "barcodes/static/src/js/barcode_parser.js",
            "barcodes_gs1_nomenclature/static/src/js/barcode_parser.js",
            "barcodes_gs1_nomenclature/static/src/js/barcode_service.js",
            # report download utils
            "web/static/src/webclient/actions/reports/utils.js",
            # PoS files
            "point_of_sale/static/src/**/*",
            ("remove", "point_of_sale/static/src/backend/**/*"),
            ("remove", "point_of_sale/static/src/customer_display/**/*"),
            "point_of_sale/static/src/customer_display/utils.js",
            # main.js boots the pos app, it is only included in the prod bundle as tests mount the app themselves
            ("remove", "point_of_sale/static/src/app/main.js"),
            ("include", "point_of_sale.base_tests"),
            # account tax engine: base_tax owns the JS mirror; account re-exports it
            "base_tax/static/src/helpers/*.js",
            "account/static/src/helpers/*.js",
            "account/static/src/services/account_move_service.js",
            "mail/static/src/core/common/sound_effects_service.js",
            "web/static/src/core/browser/router.js",
            "web/static/src/services/debug/**/*",
            "web/static/src/model/**/*",
            "web/static/src/fields/**/*",
            "web/static/src/views/**/*",
            "web/static/src/search/**/*",
            "web/static/src/webclient/actions/**/*",
            ("remove", "web/static/src/webclient/actions/reports/layout_assets/**/*"),
            ("remove", "web/static/src/webclient/actions/**/*css"),
            "partner_autocomplete/static/src/**/*",
            "google_address_autocomplete/static/src/**/*",
            # The globs above reach past web._assets_core into fields/, views/
            # and search/, so they need the same dark exclusion it makes.
            # point_of_sale.assets_prod_dark adds the tree back by glob.
            ("remove", "web/static/src/**/*.dark.scss"),
            # This module's own siblings answer the backend kanban dashboard,
            # not the PoS UI: `point_of_sale/static/src/**/*` above reaches
            # pos_dashboard.dark.scss, which web.assets_web_dark declares.
                    ],
        "point_of_sale.base_tests": [
            "web/static/lib/hoot-dom/**/*",
            "web_tour/static/src/js/**/*",
            "web_tour/static/src/tour_utils.js",
            "barcodes/static/tests/legacy/helpers.js",
            "web/static/tests/helpers/utils.js",
            "web/static/tests/helpers/cleanup.js",
            "iot_base/static/src/network_utils/*",
            "iot_base/static/src/device_controller.js",
        ],
        # Bundle that starts the pos, loaded on /pos/ui
        "point_of_sale.assets_prod": [
            ("include", "point_of_sale._assets_pos"),
            "point_of_sale/static/src/app/main.js",
        ],
        # The same three directives web.assets_web_dark carries, for the same
        # reason: without them this resolved the light palette and came out
        # byte-identical to point_of_sale.assets_prod, so `pos_assets_index`
        # served a dark-scheme user a light PoS. It only ever looked dark
        # because pos_enterprise contributed the mechanism -- which is a theme
        # supplying what the base module owes, the arrangement the webclient
        # gave up when dark mode moved from web_enterprise into web.
        "point_of_sale.assets_prod_dark": [
            ("include", "point_of_sale.assets_prod"),
            ("include", "web._dark_mode_variables"),
            (
                "after",
                "web/static/lib/bootstrap/scss/_functions.scss",
                "web/static/src/scss/bs_functions_overridden.dark.scss",
            ),
            "web/static/src/**/*.dark.scss",
        ],
        "point_of_sale.customer_display_assets": [
            ("include", "point_of_sale.base_app"),
            "point_of_sale/static/src/app/components/odoo_logo/*",
            "point_of_sale/static/src/app/components/orderline/*",
            "point_of_sale/static/src/app/components/centered_icon/*",
            "point_of_sale/static/src/app/utils/use_timed_press.js",
            "point_of_sale/static/src/utils.js",
            "point_of_sale/static/src/customer_display/**/*",
        ],
        "point_of_sale.customer_display_assets_test": [
            ("include", "point_of_sale.base_tests"),
            "point_of_sale/static/tests/pos/tours/utils/common.js",
            "point_of_sale/static/tests/generic_helpers/order_widget_util.js",
            "point_of_sale/static/tests/generic_helpers/utils.js",
            "point_of_sale/static/tests/customer_display/customer_display_utils.js",
            "point_of_sale/static/tests/customer_display/customer_display_tour.js",
        ],
        "point_of_sale.assets_debug": [
            ("include", "point_of_sale.base_tests"),
            "barcodes/static/tests/legacy/helpers.js",
            "point_of_sale/static/tests/generic_helpers/**/*",
            "point_of_sale/static/tests/pos/tours/**/*",
        ],
    },
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "esm": {
        "bundles": [
            "point_of_sale._assets_pos",
            "point_of_sale.assets_prod",
            "point_of_sale.assets_prod_dark",
            "point_of_sale.base_app",
            "point_of_sale.customer_display_assets",
            # The customer-display test bundle pulls in web_tour and hoot-dom,
            # which are module-syntax. Undeclared, every one of those files was
            # dropped from the bundle with only a console error ("cannot be
            # concatenated into non-ESM bundle"), so the tour helpers never
            # loaded and every customer-display tour failed to start.
            "point_of_sale.customer_display_assets_test",
            # Same story on the POS page itself: ``assets_debug`` includes
            # ``point_of_sale.base_tests``, which pulls web_tour and hoot-dom.
            # Undeclared, those were dropped from the bundle, the Owl templates
            # they register never loaded, and every fake tour died on a missing
            # ``point_of_sale.Loader``.
            "point_of_sale.assets_debug",
        ],
        # ``/pos/ui`` renders ``web.assets_tests`` in test mode; declaring it a
        # secondary of the POS app bundles makes the served import map carry the
        # singleton-preserving bridges (``@web/core/browser/browser`` →
        # ``odoo.loader.modules`` shim), so a test patching ``browser`` reaches
        # the running app instead of a re-bundled copy. Both the light and dark
        # prod bundles can be the page's first (import-map-winning) ESM bundle.
        # ``assets_debug`` is rendered last on that same page (after the app
        # bundle and after ``web.assets_tests``), so it needs the same treatment
        # for the same reason: its tour helpers have to drive the running app's
        # ``browser``/``registry``, not a second copy esbuild would otherwise
        # inline. Listed under BOTH prod bundles because either one can be the
        # page's first bundle, depending on the ``pos_color_scheme`` cookie.
        "secondary_import_map_includes": {
            "point_of_sale.assets_prod": [
                "web.assets_tests",
                "point_of_sale.assets_debug",
            ],
            "point_of_sale.assets_prod_dark": [
                "web.assets_tests",
                "point_of_sale.assets_debug",
            ],
            # Same shape on the customer-display page: the app bundle is the
            # first (import-map-winning) ESM bundle and the test bundle is
            # rendered after it, so it must share the app's module singletons
            # rather than resolve to re-bundled copies.
            "point_of_sale.customer_display_assets": [
                "point_of_sale.customer_display_assets_test"
            ],
        },
    },
}
