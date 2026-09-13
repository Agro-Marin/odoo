/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Dropdown } from "@web/libs/bootstrap";
import { MegaMenuDropdown } from "@website/interactions/dropdown/mega_menu_dropdown";

const log = makeLogger("website.interaction.mega_menu_dropdown.edit");

const MegaMenuDropdownEdit = (I) =>
    class extends I {
        dynamicContent = {
            ...this.dynamicContent,
            ".o_mega_menu_toggle": {
                ...this.dynamicContent[".o_mega_menu_toggle"],
                "t-on-click": (ev) => {
                    const toggleEl = ev.currentTarget;
                    const megaMenuEl =
                        toggleEl.parentElement.querySelector(".o_mega_menu");
                    log.logic("MegaMenuDropdownEdit toggle click", () => ({
                        hasMegaMenu: !!megaMenuEl,
                        shown: !!megaMenuEl?.classList.contains("show"),
                    }));
                    if (!megaMenuEl || !megaMenuEl.classList.contains("show")) {
                        this.websiteEditService.callShared(
                            "builderOptions",
                            "deactivateContainers",
                        );
                    } else {
                        this.websiteEditService.callShared(
                            "builderOptions",
                            "updateContainers",
                            megaMenuEl,
                        );
                    }
                },
            },
        };

        setup() {
            super.setup();
            this.websiteEditService = this.services.website_edit;
            log.lifecycle("MegaMenuDropdownEdit setup", () => ({
                toggles: this.el.querySelectorAll(".o_mega_menu_toggle").length,
            }));

            this.registerCleanup(() => {
                const megaMenuToggleEls = this.el.querySelectorAll(
                    ".o_mega_menu_toggle.show",
                );
                log.lifecycle(
                    "MegaMenuDropdownEdit cleanup: dispose open toggles",
                    () => ({
                        open: megaMenuToggleEls.length,
                    }),
                );
                for (const megaMenuToggleEl of megaMenuToggleEls) {
                    const bsDropdown = Dropdown.getOrCreateInstance(megaMenuToggleEl);
                    bsDropdown.hide();
                    bsDropdown.dispose();
                }
            });
        }
    };

registry.category("public.interactions.edit").add("website.mega_menu_dropdown", {
    Interaction: MegaMenuDropdown,
    mixin: MegaMenuDropdownEdit,
});
