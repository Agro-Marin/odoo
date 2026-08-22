// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { useEnvDebugContext } from "@web/core/debug/debug_context";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { groupBy, sortBy } from "@web/core/utils/collections/arrays";

const debugSectionRegistry = registry.category("debug_section");

debugSectionRegistry.addValidation({
    label: String,
    sequence: { type: Number, optional: true },
});

debugSectionRegistry
    .add("record", { label: _t("Record"), sequence: 10 })
    .add("records", { label: _t("Records"), sequence: 10 })
    .add("ui", { label: _t("User Interface"), sequence: 20 })
    .add("security", { label: _t("Security"), sequence: 30 })
    .add("testing", { label: _t("Tours & Testing"), sequence: 40 })
    .add("tools", { label: _t("Tools"), sequence: 50 });

export class DebugMenuBasic extends Component {
    static template = "web.DebugMenu";
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = {};

    setup() {
        /** @type {any} */
        this.debugContext = useEnvDebugContext();
    }

    /**
     * @returns {Promise<void>}
     */
    async loadGroupedItems() {
        const items = await this.debugContext.getItems(this.env);
        const sections = groupBy(items, (item) => item.section || "");
        this.sectionEntries = sortBy(
            Object.entries(sections),
            ([section]) =>
                debugSectionRegistry.get(section, /** @type {any} */ ({ sequence: 50 }))
                    .sequence,
        );
    }

    /**
     * @param {string} section
     * @returns {string}
     */
    getSectionLabel(section) {
        return debugSectionRegistry.get(
            section,
            /** @type {any} */ ({ label: section }),
        ).label;
    }
}
