// @ts-check
/** @odoo-module native */
import { DiscussClientAction } from "@mail/core/public_web/discuss_client_action";
import { whenReady } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { mountComponent } from "@web/env";
import { MainComponentsContainer } from "@web/ui/main_components_container";

const log = makeLogger("mail.discuss.public");

(async function boot() {
    const endBoot = log.perf("boot");
    await whenReady();

    registry.category("main_components").add("DiscussClientAction", {
        Component: DiscussClientAction,
    });

    await mountComponent(MainComponentsContainer, document.body, {
        beforeMount: (env) => {
            log.lifecycle("beforeMount", () => ({
                models: Object.keys(odoo.discuss_data || {}),
            }));
            env.services["mail.store"].insert(odoo.discuss_data);
            odoo.isReady = true;
        },
    });
    endBoot();
})();
