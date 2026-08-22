/** @odoo-module native */
import { DiscussClientAction } from "@mail/core/public_web/discuss_client_action";
import { whenReady } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { mountComponent } from "@web/env";
import { MainComponentsContainer } from "@web/ui/main_components_container";

// Kept self-executing and unsplit, unlike `spreadsheet/public_readonly_app`.
// Extracting the sequence would only be worth it if it became testable, and
// nothing here reaches a test bundle: `discuss/core/public/**` lives in
// `mail.assets_public` alone. Adding it to `web.assets_unit_tests_setup` would
// drag `discuss_patch.js`, `store_service_patch.js`, `discuss_app_model_patch.js`
// and `discuss_client_action_patch.js` in with it — four modules that `patch()`
// at import time — and apply the public-Discuss behaviour to every mail test.
// This page is covered by tours instead; see `mail/tests/discuss/`.
(async function boot() {
    await whenReady();

    // Before `mountComponent`, which starts the services that render it.
    registry.category("main_components").add("DiscussClientAction", {
        Component: DiscussClientAction,
    });

    await mountComponent(MainComponentsContainer, document.body, {
        beforeMount: (env) => {
            // Between `startServices` and the first render: the store has to
            // hold the page's data before anything asks it to draw, and
            // `odoo.isReady` was already set before the mount here — it is a
            // tour contract, so it stays exactly where it was.
            env.services["mail.store"].insert(odoo.discuss_data);
            odoo.isReady = true;
        },
    });
})();
