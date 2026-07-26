// @ts-check
/** @odoo-module native */

/** @module @web/webclient/switch_company_menu/switch_company_menu - Company switcher systray dropdown with multi-select, search, and access-rights verification */

import { Component, useChildSubEnv, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownGroup } from "@web/components/dropdown/dropdown_group";
import { useDropdownState } from "@web/components/dropdown/dropdown_hooks";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { UserEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus, useChildRef, useService } from "@web/core/utils/hooks";
import { useCommand } from "@web/services/commands/command_hook";
import { useHotkey } from "@web/services/hotkeys/hotkey_hook";
import { user, userBus } from "@web/services/user";
import {
    CompanySelector,
    getCompany,
} from "@web/webclient/switch_company_menu/company_selector";
import { SwitchCompanyItem } from "@web/webclient/switch_company_menu/switch_company_item";

/**
 * Systray dropdown for switching between companies in a multi-company environment.
 *
 * Supports search filtering, keyboard navigation, select-all, and applies
 * company changes via the router (with access-rights verification).
 */
export class SwitchCompanyMenu extends Component {
    static template = "web.SwitchCompanyMenu";
    static components = {
        Dropdown,
        DropdownItem,
        DropdownGroup,
        SwitchCompanyItem,
    };
    static props = {};
    // Exposed as a static so subclasses/patches can swap the model, and so
    // tests can drive it without mounting the component.
    static CompanySelector = CompanySelector;

    setup() {
        this.dropdown = useDropdownState();
        this.user = user;
        const actionService = useService("action");

        this.companySelector = useState(
            new /** @type {any} */ (this.constructor).CompanySelector(
                actionService,
                this.dropdown,
            ),
        );
        useChildSubEnv({ companySelector: this.companySelector });

        this.searchInputRef = useRef("inputRef");
        this.state = useState(
            /** @type {{ searchFilter: string, showFilter: boolean, visibleCompanies: any[] }} */ ({}),
        );
        this.resetState();

        // Both the confirm hotkey and the "Switch Company" command act on
        // this.dropdown, which only the desktop template renders. On small
        // screens the switcher is the MobileSwitchCompanyMenu subclass, whose
        // visibility is driven by its own collapsible (state.isOpen), so these
        // would register a dead command-palette entry and a hotkey whose
        // isAvailable (this.dropdown.isOpen) can never become true. Skip them
        // there instead of shipping silent no-ops.
        if (!this.env.isSmall) {
            useHotkey("control+enter", () => this.confirm(), {
                bypassEditableProtection: true,
                // The hotkey lives for the component's lifetime: without the
                // isOpen guard, a draft selection surviving a close could be
                // applied by a later Ctrl+Enter pressed anywhere in the app.
                isAvailable: () =>
                    this.dropdown.isOpen && this.companySelector.hasSelectionChanged,
            });

            useCommand(_t("Switch Company"), () => this.dropdown.open(), {
                hotkey: "alt+shift+u",
            });
        }
        useBus(userBus, UserEvent.ACTIVE_COMPANIES_CHANGED, () => {
            this.companySelector.reset();
        });

        this.containerRef = useChildRef();
        this.navigationOptions = {
            hotkeys: {
                space: (navigator) => {
                    const navItem = navigator.activeItem;
                    if (!navItem) {
                        return;
                    }
                    if (navItem.el.classList.contains("o_switch_company_item")) {
                        const companyId = Number.parseInt(
                            navItem.el.dataset.companyId,
                            10,
                        );
                        this.companySelector.switchCompany("toggle", companyId);
                    }
                },
                enter: (navigator) => {
                    const navItem = navigator.activeItem;
                    if (!navItem) {
                        return;
                    }
                    if (navItem.el.classList.contains("o_switch_company_item")) {
                        const companyId = Number.parseInt(
                            navItem.el.dataset.companyId,
                            10,
                        );
                        this.companySelector.switchCompany("loginto", companyId);
                        this.dropdown.close();
                    } else {
                        navItem.select();
                    }
                },
            },
        };
    }

    get hasLotsOfCompanies() {
        return user.allowedCompaniesWithAncestors.length > 9;
    }

    get visibleCompanies() {
        return this.state.visibleCompanies;
    }

    get hasSelectedCompanies() {
        return this.visibleCompanies.some((c) =>
            this.companySelector.isCompanySelected(c.company.id),
        );
    }

    get selectAllClass() {
        if (
            this.visibleCompanies.every((c) =>
                this.companySelector.isCompanySelected(c.company.id),
            )
        ) {
            return "btn-link text-primary";
        } else {
            return "btn-link text-secondary";
        }
    }

    get selectAllIcon() {
        if (
            this.visibleCompanies.every((c) =>
                this.companySelector.isCompanySelected(c.company.id),
            )
        ) {
            return "fa-solid fa-square-check text-primary";
        } else if (
            this.visibleCompanies.some((c) =>
                this.companySelector.isCompanySelected(c.company.id),
            )
        ) {
            return "fa-regular fa-square-minus";
        } else {
            return "fa-regular fa-square";
        }
    }

    computeVisibleCompanies() {
        const companies = [];

        const addCompany = (company, level = 0) => {
            if (this.matchSearch(company.name)) {
                companies.push({ company, level });
            }

            if (company.child_ids) {
                for (const companyId of company.child_ids) {
                    addCompany(getCompany(companyId), level + 1);
                }
            }
        };

        user.allowedCompaniesWithAncestors
            .filter((c) => !c.parent_id)
            .sort((c1, c2) => c1.sequence - c2.sequence)
            .forEach((c) => addCompany(c));

        return companies;
    }

    resetState() {
        this.state.searchFilter = "";
        this.state.showFilter = this.hasLotsOfCompanies;
        this.state.visibleCompanies = this.computeVisibleCompanies();
    }

    onSearch(ev) {
        this.state.searchFilter = ev.target.value;
        this.state.showFilter = true;
        this.state.visibleCompanies = this.computeVisibleCompanies();
    }

    matchSearch(companyName) {
        if (!this.state.searchFilter) {
            return true;
        }

        const name = companyName.toLocaleLowerCase().replace(/\s/g, "");
        const filter = this.state.searchFilter.toLocaleLowerCase().replace(/\s/g, "");
        return name.includes(filter);
    }

    handleDropdownChange(isOpen) {
        if (isOpen) {
            if (this.searchInputRef.el) {
                this.searchInputRef.el.focus();
            }

            if (/** @type {any} */ (this.containerRef).el) {
                // Fixes the container width so it doesn't change when searching.
                const currentWidth = /** @type {any} */ (
                    this.containerRef
                ).el.getBoundingClientRect().width;
                /** @type {any} */ (this.containerRef).el.style.width =
                    `${currentWidth}px`;
            }
        } else {
            this.resetState();
            // Closing without confirming discards the draft selection:
            // reset() re-seeds it from the currently active companies, so
            // pending toggles cannot be applied by a later confirm.
            this.companySelector.reset();
        }
    }

    confirm() {
        // Apply before closing (as the "loginto" path does): closing
        // triggers handleDropdownChange(false), which resets the draft
        // selection that apply() must still read.
        this.companySelector.apply();
        this.dropdown.close();
    }

    selectAll() {
        const companyIds = this.visibleCompanies.map((entry) => entry.company.id);
        this.companySelector.toggleSelectAll(companyIds);
    }

    get isSingleCompany() {
        return user.allowedCompaniesWithAncestors.length === 1;
    }
}

export const systrayItem = {
    Component: SwitchCompanyMenu,
};

registry.category("systray").add("SwitchCompanyMenu", systrayItem, { sequence: 1 });
