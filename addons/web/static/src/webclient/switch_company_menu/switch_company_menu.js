// @ts-check
/** @odoo-module native */

/** @module @web/webclient/switch_company_menu/switch_company_menu */

import { Component, useChildSubEnv, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownGroup } from "@web/components/dropdown/dropdown_group";
import { useDropdownState } from "@web/components/dropdown/dropdown_hooks";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { UserEvent } from "@web/core/events";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user, userBus } from "@web/core/user";
import { useBus, useChildRef, useService } from "@web/core/utils/hooks";
import { useCommand } from "@web/ui/commands/command_hook";
import {
    CompanySelector,
    getCompany,
} from "@web/webclient/switch_company_menu/company_selector";
import { SwitchCompanyItem } from "@web/webclient/switch_company_menu/switch_company_item";

export class SwitchCompanyMenu extends Component {
    static template = "web.SwitchCompanyMenu";
    static components = {
        Dropdown,
        DropdownItem,
        DropdownGroup,
        SwitchCompanyItem,
    };
    static props = {};
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

        if (!this.env.isSmall) {
            useHotkey("control+enter", () => this.confirm(), {
                bypassEditableProtection: true,
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

    /** @returns {string} */
    get selectAllTitle() {
        return this.hasSelectedCompanies ? _t("Deselect all") : _t("Select all");
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

    /**
     * The filter selects subtrees, not rows.
     *
     * Selection cascades: `_selectCompany` recurses into `child_ids`, so
     * acting on a company acts on its branches whether or not they are on
     * screen. Matching row by row therefore lied in both directions -- a
     * matched branch rendered indented under nothing, and "select all" over a
     * filtered list quietly took in companies the user could not see.
     *
     * So visibility is closed under descendants: a company is shown when its
     * subtree holds a match, and showing it shows everything under it. What is
     * on screen is then exactly what the controls act on, and every rendered
     * row still sits below its parent.
     */
    computeVisibleCompanies() {
        /** @type {Map<number, boolean>} subtree holds a match */
        const inSubtree = new Map();
        const scanSubtree = (company) => {
            let found = this.matchSearch(company.name);
            for (const companyId of company.child_ids || []) {
                // Every child is scanned: `found` short-circuiting here would
                // leave the map incomplete for the pass below.
                if (scanSubtree(getCompany(companyId))) {
                    found = true;
                }
            }
            inSubtree.set(company.id, found);
            return found;
        };

        const companies = [];
        const emit = (company, level, ancestorShown) => {
            const shown = ancestorShown || inSubtree.get(company.id);
            if (shown) {
                companies.push({ company, level });
            }
            for (const companyId of company.child_ids || []) {
                emit(getCompany(companyId), level + 1, shown);
            }
        };

        const roots = user.allowedCompaniesWithAncestors
            .filter((c) => !c.parent_id)
            .sort((c1, c2) => c1.sequence - c2.sequence);
        roots.forEach(scanSubtree);
        roots.forEach((c) => emit(c, 0, false));

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
                const currentWidth = /** @type {any} */ (
                    this.containerRef
                ).el.getBoundingClientRect().width;
                /** @type {any} */ (this.containerRef).el.style.width =
                    `${currentWidth}px`;
            }
        } else {
            this.resetState();
            this.companySelector.reset();
        }
    }

    confirm() {
        Promise.resolve(this.companySelector.apply()).catch((error) => {
            console.warn("Failed to apply the company selection", error);
        });
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
