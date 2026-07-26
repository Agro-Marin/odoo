/** @odoo-module native */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { BurgerMenu } from "@web/webclient/burger_menu/burger_menu";

const websiteSystrayRegistry = registry.category("website_systray");

patch(BurgerMenu.prototype, {
    setup() {
        super.setup();
        this.websiteCustomMenus = useService("website_custom_menus");

        if (!websiteSystrayRegistry.contains("burger_menu")) {
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

    /**
     * No-op setter paired with the getter above — see the note on
     * ``web``'s ``NavBar.set currentAppSections``. ``patch()`` installs
     * descriptors verbatim, so a getter-only extension leaves the accessor
     * without a setter and any assignment throws in strict mode.
     *
     * NB: unlike the navbar case there is no ancestor here — ``web``'s
     * ``BurgerMenu`` declares no ``currentAppSections`` at all, so the
     * ``super`` call in the getter above resolves to ``undefined`` unless
     * another patch supplies it.
     */
    set currentAppSections(_) {},

    /**
     * @override
     */
    async _onMenuClicked(menu) {
        const websiteMenu = this.websiteCustomMenus.get(menu.xmlid);
        if (websiteMenu) {
            await this.websiteCustomMenus.open(menu);
            this._closeBurger();
        } else {
            super._onMenuClicked(menu);
        }
    },
});
