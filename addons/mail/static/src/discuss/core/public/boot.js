/** @odoo-module native */
import { DiscussClientAction } from "@mail/core/public_web/discuss_client_action";
import { whenReady } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { mountComponent } from "@web/env";
import { MainComponentsContainer } from "@web/ui/main_components_container";

(async function boot() {
    await whenReady();

    registry.category("main_components").add("DiscussClientAction", {
        Component: DiscussClientAction,
    });

    await mountComponent(MainComponentsContainer, document.body, {
        beforeMount: (env) => {
            env.services["mail.store"].insert(odoo.discuss_data);
            odoo.isReady = true;
        },
    });
})();
