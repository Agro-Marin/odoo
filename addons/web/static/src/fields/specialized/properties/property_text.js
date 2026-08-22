// @ts-check
/** @odoo-module native */

import { Component, useRef } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";
import { useAutoresize } from "@web/core/utils/dom/autoresize";
import { useBus } from "@web/core/utils/hooks";
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
            useBus(this.props.record.model.bus, ModelEvent.NEED_LOCAL_CHANGES, flush);
            useBus(this.props.record.model.bus, ModelEvent.WILL_SAVE_URGENTLY, flush);
        }
    }
}
