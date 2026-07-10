// @ts-check
/** @odoo-module native */

/** @module @web/webclient/debug/field_widgets_dialog - Debug dialog listing every registered field widget */

import { Component, useState, xml } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { Dialog } from "@web/ui/dialog/dialog";

/**
 * Modal dialog listing every entry in the ``fields`` registry, with a
 * client-side search filter.  Answers "which widget should I use?" without
 * grepping the source.
 *
 * Read-only — does not modify the registry.  Snapshot is taken on mount;
 * widgets registered after the dialog opens won't appear until reopen.
 */
export class FieldWidgetsDialog extends Component {
    static components = { Dialog };
    static props = {
        close: Function,
    };
    static template = xml`
        <Dialog title="title" size="'lg'">
            <div class="o_field_widgets_inspector">
                <div class="d-flex align-items-center gap-2 mb-2">
                    <input
                        type="search"
                        class="form-control flex-grow-1"
                        placeholder="Filter by name, display name, or supported type…"
                        t-model="state.filter"
                        autofocus="true"
                    />
                    <small class="text-muted text-nowrap">
                        <t t-esc="filteredEntries.length"/> / <t t-esc="entries.length"/>
                    </small>
                </div>
                <div class="table-responsive" style="max-height: 60vh">
                    <table class="table table-sm table-hover table-striped mb-0">
                        <thead class="position-sticky top-0 bg-white">
                            <tr>
                                <th>Name</th>
                                <th>Display name</th>
                                <th>Supported types</th>
                                <th>Component</th>
                                <th class="text-end">Options</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr t-foreach="filteredEntries" t-as="entry" t-key="entry[0]">
                                <td><code t-esc="entry[0]"/></td>
                                <td t-esc="displayName(entry[1])"/>
                                <td t-esc="supportedTypes(entry[1])"/>
                                <td><code t-esc="componentName(entry[1])"/></td>
                                <td class="text-end" t-esc="optionCount(entry[1])"/>
                            </tr>
                            <tr t-if="!filteredEntries.length">
                                <td colspan="5" class="text-center text-muted py-3">
                                    No widgets match the filter.
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </Dialog>`;

    setup() {
        this.title = _t("Field Widgets");
        this.entries = [...registry.category("fields").getEntries()].sort(([a], [b]) =>
            a.localeCompare(b),
        );
        this.state = useState({ filter: "" });
    }

    get filteredEntries() {
        const filter = this.state.filter.trim().toLowerCase();
        if (!filter) {
            return this.entries;
        }
        return this.entries.filter(([key, value]) => {
            if (key.toLowerCase().includes(filter)) {
                return true;
            }
            const display = String(value?.displayName ?? "").toLowerCase();
            if (display.includes(filter)) {
                return true;
            }
            return (value?.supportedTypes ?? []).some((t) =>
                String(t).toLowerCase().includes(filter),
            );
        });
    }

    displayName(value) {
        return String(value?.displayName ?? "—");
    }

    supportedTypes(value) {
        const types = value?.supportedTypes ?? [];
        return types.length ? types.join(", ") : "—";
    }

    componentName(value) {
        return value?.component?.name ?? "—";
    }

    optionCount(value) {
        return value?.supportedOptions?.length ?? 0;
    }
}
