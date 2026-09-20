/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

const log = makeLogger("website.client_action.open_custom_menu");

export async function openCustomMenu(env, action) {
    const websiteCustomMenus = env.services["website_custom_menus"];
    const websiteMenu = websiteCustomMenus.get(action.context.xmlid);
    log.logic("openCustomMenu", () => ({
        xmlid: action.context.xmlid,
        found: Boolean(websiteMenu),
    }));
    if (websiteMenu) {
        websiteCustomMenus.open({ xmlid: action.context.xmlid });
    }
}

registry.category("actions").add("open_website_custom_menu", openCustomMenu);
