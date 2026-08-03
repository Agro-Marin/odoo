/** @odoo-module native */
import { DiscussClientAction } from "@mail/core/public_web/discuss_client_action";
import { mount, whenReady } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { appTranslateFn } from "@web/core/translation";
import { makeEnv, startServices } from "@web/env";
import { MainComponentsContainer } from "@web/ui/main_components_container";

(async function boot() {
    await whenReady();

    const mainComponentsRegistry = registry.category("main_components");
    mainComponentsRegistry.add("DiscussClientAction", {
        Component: DiscussClientAction,
    });

    const env = makeEnv();
    await startServices(env);
    env.services["mail.store"].insert(odoo.discuss_data);
    odoo.isReady = true;
    const root = await mount(MainComponentsContainer, document.body, {
        env,
        getTemplate,
        dev: env.debug,
        translatableAttributes: ["data-tooltip"],
        translateFn: appTranslateFn,
    });
    odoo.__WOWL_DEBUG__ = { root };
})();
