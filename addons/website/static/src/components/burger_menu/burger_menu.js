/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { BurgerMenu } from "@web/webclient/burger_menu/burger_menu";

const websiteSystrayRegistry = registry.category("website_systray");

const log = makeLogger("website.component.burger_menu");

patch(BurgerMenu.prototype, {
    setup() {
        super.setup();
        this.websiteCustomMenus = useService("website_custom_menus");

        if (!websiteSystrayRegistry.contains("burger_menu")) {
            log.logic("BurgerMenu register in website systray");
            websiteSystrayRegistry.add(
                "burger_menu",
                registry.category("systray").get("burger_menu"),
                { sequence: 0 },
            );
        }
    },

    /**
     * @override
     */
    get currentAppSections() {
        const currentAppSections = super.currentAppSections;
        if (
            this.currentApp &&
            this.currentApp.xmlid === "website.menu_website_configuration"
        ) {
            return this.websiteCustomMenus
                .addCustomMenus(currentAppSections)
                .filter((section) => section.childrenTree.length);
        }
        return currentAppSections;
    },

    set currentAppSections(_) {},

    /**
     * @override
     */
    async _onMenuClicked(menu) {
        const websiteMenu = this.websiteCustomMenus.get(menu.xmlid);
        log.logic("BurgerMenu menu clicked", () => ({
            xmlid: menu.xmlid,
            websiteMenu: Boolean(websiteMenu),
        }));
        if (websiteMenu) {
            await this.websiteCustomMenus.open(menu);
            this._closeBurger();
        } else {
            super._onMenuClicked(menu);
        }
    },
});
