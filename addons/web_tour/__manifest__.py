# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Tours',
    'category': 'Hidden',
    'description': """
Odoo Web tours.
========================

""",
    'version': '1.0',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'views/tour_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'web_tour/static/src/scss/**/*',
            'web_tour/static/src/js/tour_pointer/**/*',
            'web_tour/static/src/js/utils/**/*',
            'web_tour/static/src/js/tour_state.js',
            'web_tour/static/src/js/tour_service.js',
            'web_tour/static/src/js/tour_recorder/tour_recorder_state.js',
            'web_tour/static/src/tour_utils.js',
            'web_tour/static/src/js/onboarding_item.xml',
            'web_tour/static/src/views/**/*',
            'web_tour/static/src/widgets/**/*',
        ],
        'web.assets_frontend': [
            'web_tour/static/src/scss/**/*',
            'web_tour/static/src/js/tour_pointer/**/*',
            'web_tour/static/src/js/utils/**/*',
            'web_tour/static/src/js/tour_state.js',
            'web_tour/static/src/js/tour_service.js',
            'web_tour/static/src/js/tour_recorder/tour_recorder_state.js',
            'web_tour/static/src/tour_utils.js',
            'web_tour/static/src/js/onboarding_item.xml',
        ],
        'web.assets_unit_tests': [
            ('include', 'web_tour.recorder'),
            ('include', 'web_tour.automatic'),
            ('include', 'web_tour.interactive'),
            'web_tour/static/tests/*.test.js',
        ],
        # ``web_tour.automatic`` is preloaded into ``web.assets_web`` via
        # the ``esm.dynamic_children`` declaration at the bottom of this
        # manifest (separate ESM child bundle).  Including its modules into ``web.assets_tests`` again
        # would bundle a SECOND copy of ``tour_helpers.js`` — each bundle
        # gets its own ``TourHelpers`` class, the patches in
        # ``tour_helpers_hoot.js`` apply to one prototype while
        # ``tour_step_automatic.js`` instantiates the other, and every
        # ``run: "click"`` step throws ``TypeError: actionHelper.click is
        # not a function``.  The lazy ``loadBundle("web_tour.automatic")``
        # in ``tour_service.js`` is a no-op once the parent loads, so the
        # preload optimisation is moot here.
        "web.assets_tests": [],
        'web_tour._common': [
            'web/static/lib/hoot-dom/**/*',
            'web_tour/static/src/js/tour_step.js',
        ],
        'web_tour.interactive': [
            ('include', 'web_tour._common'),
            'web_tour/static/src/js/tour_interactive/**/*',
        ],
        'web_tour.automatic': [
            ('include', 'web_tour._common'),
            'web_tour/static/src/js/tour_automatic/**/*',
        ],
        # The recorder UI only. `views/` (the tour list view) and `widgets/`
        # (the tour_start form widget) are backend screens that
        # `web.assets_backend` already ships above; carrying them here put a
        # second copy of each in a lazily-loaded bundle, and they are what
        # dragged `@web/views/list` and `@web/fields/basic/char/char_field`
        # into the recorder's import map -- backend modules a frontend page
        # never registers, so their bridges resolved to `undefined` and
        # `TourRecorder extends Component` died before it drew anything.
        # `tour_service.js` ships on the frontend too and loads this there.
        'web_tour.recorder': [
            ('include', 'web_tour._common'),
            'web_tour/static/src/js/tour_recorder/**/*',
        ],
    },
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
    'esm': {
        'bundles': [
            'web_tour.automatic',
            'web_tour.interactive',
            'web_tour.recorder',
        ],
        # The parent->child links mirror wherever the *loader* ships, not just
        # the backend. ``tour_service.js`` is listed in both
        # ``web.assets_backend`` (reached through ``web.assets_web``) and
        # ``web.assets_frontend`` above, and it can lazily ``loadBundle`` all
        # three of these from either one: ``startTour`` pulls
        # ``web_tour.automatic`` / ``web_tour.interactive``, and the
        # localStorage-driven branch at the end of the service pulls
        # ``web_tour.recorder``.
        #
        # A missing link is not a missed optimisation but a hard failure:
        # ``dynamic_children`` is what merges a child's import map into the
        # page's (``ir_qweb_assets._merge_child_import_maps``), and dynamic
        # children are served per-file, so without the frontend entry the
        # ``import("@web_tour/js/tour_automatic/...")`` after ``loadBundle``
        # dies with "Failed to resolve module specifier" and no tour can start
        # on a frontend page. Portal deliberately supports tours there: its
        # ``ir.http`` override feeds ``tour_enabled`` / ``current_tour`` into
        # the *frontend* session info so a tour survives a redirect into /my.
        #
        # The frontend entry is declared on ``web.assets_frontend`` (where
        # ``tour_service.js`` actually is) rather than on the composed
        # ``web.assets_frontend_lazy`` that pages render: child resolution
        # follows the include graph, see
        # ``ir_qweb_assets._get_dynamic_parent_bundles``.
        'dynamic_children': {
            'web.assets_web': [
                'web_tour.automatic',
                'web_tour.interactive',
                'web_tour.recorder',
            ],
            'web.assets_frontend': [
                'web_tour.automatic',
                'web_tour.interactive',
                'web_tour.recorder',
            ],
            # Same rule, third parent: ``web.assets_unit_tests_setup`` pulls in
            # ``web.assets_backend``, so ``tour_service.js`` and its lazy
            # ``import()`` calls ship there too.  Without the link esbuild has
            # no ``--external`` for those specifiers and inlines a copy into
            # the setup bundle, while ``web.assets_unit_tests`` -- which
            # includes the same three child bundles -- publishes them again as
            # per-file import-map entries.  Test files then resolve the
            # specifier to the source URL while the application code inside the
            # bundle resolves to its own copy, so
            # ``patchWithCleanup(TourRecorder.prototype, ...)`` patches a
            # prototype the mounted component was never built from.
            'web.assets_unit_tests_setup': [
                'web_tour.automatic',
                'web_tour.interactive',
                'web_tour.recorder',
            ],
        },
    },
}
