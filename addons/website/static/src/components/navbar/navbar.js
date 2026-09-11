/** @odoo-module native */
import { useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";
import { UserMenu } from "@web/webclient/user_menu/user_menu";

const websiteSystrayRegistry = registry.category("website_systray");
websiteSystrayRegistry.add("UserMenu", { Component: UserMenu }, { sequence: 14 });

patch(NavBar.prototype, {
    setup() {
        super.setup();
        this.websiteService = useService("website");
        this.websiteCustomMenus = useService("website_custom_menus");

        useBus(websiteSystrayRegistry, "EDIT-WEBSITE", () => this.render(true));

        if (this.env.debug && !websiteSystrayRegistry.contains("web.debug_mode_menu")) {
            websiteSystrayRegistry.add(
                "web.debug_mode_menu",
                registry.category("systray").get("web.debug_mode_menu"),
                { sequence: 100 },
            );
        }
        let adaptCounter = 0;
        const renderAndAdapt = () => {
            this.render(true);
            adaptCounter++;
        };
        useEffect(
            (adaptCounter) => {
                if (adaptCounter > 0) {
                    this.adapt();
                }
            },
            () => [adaptCounter],
        );

        useBus(websiteSystrayRegistry, "CONTENT-UPDATED", renderAndAdapt);
    },

    get shouldDisplayWebsiteSystray() {
        return (
            this.websiteService.currentWebsite && this.websiteService.isRestrictedEditor
        );
    },

    set shouldDisplayWebsiteSystray(_) {},

    /**
     * @override
     */
    get systrayItems() {
        if (this.websiteService.currentWebsite) {
            const websiteItems = websiteSystrayRegistry
                .getEntries()
                .map(([key, value], index) => ({ key, ...value, index }))
                .filter((item) =>
                    "isDisplayed" in item ? item.isDisplayed(this.env) : true,
                )
                .reverse();
            if (
                !websiteItems.every((item) =>
                    ["burger_menu", "web.debug_mode_menu"].includes(item.key),
                )
            ) {
                return websiteItems;
            }
        }
        return super.systrayItems;
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
     * @override
     */
    async onNavBarDropdownItemSelection(menu) {
        const websiteMenu = this.websiteCustomMenus.get(menu.xmlid);
        if (websiteMenu) {
            return this.websiteCustomMenus.open(menu);
        }
        return super.onNavBarDropdownItemSelection(menu);
    },
});
