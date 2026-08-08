// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/ir_ui_view_ace/ir_ui_view_code_editor */

import { onMounted, useEffect } from "@odoo/owl";
import { CodeEditor } from "@web/components/code_editor/code_editor";
import { escapeRegExp } from "@web/core/utils/format/strings";
export class IrUiViewCodeEditor extends CodeEditor {
    static props = {
        .../** @type {any} */ (CodeEditor).props,
        record: { type: Object },
    };

    /** @type {Array<{ session: any, id: any }>} */
    markers = [];

    setup() {
        super.setup();
        this.markers = [];

        onMounted(() => {
            this.aceEditor.on("change", () => {
                this.clearMarkers();
            });
        });

        useEffect(
            (arch, invalid_locators) => {
                if (arch && invalid_locators) {
                    this.highlightInvalidLocators(arch, invalid_locators);
                    return () => this.clearMarkers();
                }
            },
            () => [this.props.value, this.props.record?.data.invalid_locators],
        );
    }

    /**
     * @param {string} arch
     * @param {any[]} invalid_locators
     */
    async highlightInvalidLocators(arch, invalid_locators) {
        const resModel = this.env.model?.config.resModel;
        const resId = this.env.model?.config.resId;
        if (resModel === "ir.ui.view" && resId) {
            const { doc } = this.aceEditor.session;
            for (const spec of invalid_locators) {
                if (spec.broken_hierarchy) {
                    continue;
                }
                const { tag, attrib, sourceline } = spec;
                const attribRegex = Object.entries(attrib)
                    .map(([key, value]) => {
                        const escapedValue = escapeRegExp(value).replace(
                            /"/g,
                            '("|&quot;)',
                        );
                        return (
                            `(?=[^>]*?\\b${escapeRegExp(key)}\\s*=\\s*` +
                            `(?:"[^"]*${escapedValue}[^"]*"|'[^']*${escapedValue}[^']*'))`
                        );
                    })
                    .join("");
                const nodeRegex = new RegExp(
                    `<${escapeRegExp(tag)}\\s+${attribRegex}[^>]*>`,
                    "g",
                );
                for (const match of arch.matchAll(nodeRegex)) {
                    const startIndex = match.index;
                    const endIndex = startIndex + match[0].length;
                    const startPos = doc.indexToPosition(startIndex);
                    const endPos = doc.indexToPosition(endIndex);
                    if (startPos.row + 1 === sourceline) {
                        const range = new window.ace.Range(
                            startPos.row,
                            startPos.column,
                            endPos.row,
                            endPos.column,
                        );
                        const session = this.aceEditor.session;
                        this.markers.push({
                            session,
                            id: session.addMarker(range, "invalid_locator", "text"),
                        });
                    }
                }
            }
        }
    }

    clearMarkers() {
        this.markers.forEach(({ session, id }) => session.removeMarker(id));
        this.markers = [];
    }
}
