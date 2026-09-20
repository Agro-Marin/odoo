/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { EditMenuDialog, MenuDialog } from "@website/components/dialog/edit_menu";

import { NavbarLinkPopover } from "./navbar_link_popover/navbar_link_popover.js";

const log = makeLogger("website.builder.plugin.menu_data_plugin");

/**
 * @typedef { Object } MenuDataShared
 * @property { MenuDataPlugin['openEditMenu'] } openEditMenu
 */

export class MenuDataPlugin extends Plugin {
    static id = "menuDataPlugin";
    static shared = ["openEditMenu"];
    static dependencies = ["savePlugin"];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        link_popovers: [
            withSequence(10, {
                PopoverClass: NavbarLinkPopover,
                isAvailable: (linkElement) =>
                    linkElement &&
                    linkElement.closest(
                        ".top_menu, .o_extra_menu_items, [data-content_menu_id]",
                    ) &&
                    !linkElement.closest(
                        ".dropdown-toggle, li.o_header_menu_button a, [data-toggle], .o_offcanvas_logo, .o_mega_menu",
                    ),
                getProps: (props) => ({
                    ...props,
                    onClickEditLink: (elem, callback) => {
                        const menuEl =
                            elem.props.linkElement.querySelector("[data-oe-id]");
                        log.lifecycle("MenuDialog open", () => ({
                            menuId: menuEl.dataset.oeId,
                        }));
                        this.services.dialog.add(MenuDialog, {
                            name: menuEl.textContent,
                            url: menuEl.parentElement.attributes["href"].nodeValue,
                            save: async (name, url) => {
                                const websiteId =
                                    this.services.website.currentWebsite.id;
                                const data = {
                                    id: parseInt(
                                        menuEl.attributes["data-oe-id"].nodeValue,
                                    ),
                                    name,
                                    url,
                                };
                                const endSaveMenu = log.perf(
                                    "MenuDialog save menu",
                                    () => ({
                                        websiteId,
                                        id: data.id,
                                    }),
                                );
                                const result = await this.services.orm.call(
                                    "website.menu",
                                    "save",
                                    [websiteId, { data: [data] }],
                                );
                                endSaveMenu();
                                menuEl.parentElement.attributes["href"].nodeValue = url;
                                menuEl.textContent = name;
                                callback();
                                return result;
                            },
                        });
                    },
                    onClickEditMenu: this.openEditMenu.bind(this, props.linkElement),
                }),
            }),
        ],
        is_link_editable_predicates: this.isMenuLink.bind(this),
    };

    setup() {
        log.lifecycle("setup");
        this.websiteService = this.services.website;
    }

    openEditMenu(linkEl) {
        if (this.isEditMenuOpening) {
            log.logic("openEditMenu skip: dialog already opening");
            return Promise.resolve();
        }
        this.isEditMenuOpening = true;
        return new Promise((resolve) => {
            const rootID = parseInt(
                linkEl?.closest("[data-content_menu_id]")?.dataset.content_menu_id,
            );
            log.lifecycle("EditMenuDialog open", () => ({ rootID }));
            this.services.dialog.add(
                EditMenuDialog,
                {
                    rootID: isNaN(rootID) ? null : rootID,
                    save: async (newPageUrl) => {
                        const endSave = log.perf("EditMenuDialog save page");
                        await this.dependencies.savePlugin.save();
                        endSave();
                        const endReload = log.perf("EditMenuDialog reload editor");
                        await this.config.reloadEditor();
                        endReload();
                        log.logic("EditMenuDialog save: redirect decision", {
                            newPageUrl,
                        });
                        if (newPageUrl) {
                            this.websiteService.goToWebsite({
                                path: newPageUrl,
                                edition: true,
                                websiteId: this.websiteService.currentWebsite.id,
                            });
                        }
                    },
                },
                {
                    onClose: () => {
                        log.lifecycle("EditMenuDialog close");
                        this.isEditMenuOpening = false;
                        resolve();
                    },
                },
            );
        });
    }

    /**
     * @param {HTMLElement} linkElement
     * @returns {boolean}
     */
    isMenuLink(linkElement) {
        return (
            linkElement &&
            (linkElement.getAttribute("role") === "menuitem" ||
                linkElement.classList.contains("nav-link")) &&
            !linkElement.dataset.bsToggle
        );
    }
}

registry.category("website-plugins").add(MenuDataPlugin.id, MenuDataPlugin);
