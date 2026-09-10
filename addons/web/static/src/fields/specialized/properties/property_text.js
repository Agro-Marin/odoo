// @ts-check
/** @odoo-module native */

import { Component, useRef } from "@odoo/owl";
import { useAutoresize } from "@web/core/utils/dom/autoresize";
import { useFieldFlush } from "@web/fields/hooks/debounced_field_commit";
export class PropertyText extends Component {
    static template = "web.PropertyText";
    static props = {
        updateProperty: Function,
        value: String,
        record: { type: Object, optional: true },
    };

    /** @type {import("@odoo/owl").Ref} */
    textareaRef;

    setup() {
        this.textareaRef = useRef("textarea");
        useAutoresize(/** @type {any} */ (this.textareaRef));

        if (this.props.record) {
            const flush = (/** @type {Event} */ ev) => {
                const el = this.textareaRef.el;
                if (el && el === document.activeElement) {
                    /** @type {CustomEvent} */ (ev).detail?.proms?.push(
                        this.props.updateProperty({ target: el }),
                    );
                }
            };
            useFieldFlush(this.props.record.model.bus, flush);
        }
    }
}
