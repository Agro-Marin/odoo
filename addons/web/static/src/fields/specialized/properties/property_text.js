// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/property_text - Auto-resizing textarea component for property text values */

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

    setup() {
        this.textareaRef = useRef("textarea");
        useAutoresize(/** @type {any} */ (this.textareaRef));

        // Flush a typed-but-unblurred value on save: the textarea commits only on
        // its native ``change`` (blur), but Ctrl+S (NEED_LOCAL_CHANGES) and
        // tab-close (WILL_SAVE_URGENTLY) don't blur it. Only the FOCUSED textarea
        // can hold an uncommitted value; commit it via ``updateProperty`` (same
        // path as ``change``) and let the save await the queued update. Mirrors
        // the raw-input flush in PropertyValue; ``record`` is optional so guard.
        if (this.props.record) {
            const flush = (ev) => {
                const el = this.textareaRef.el;
                if (el && el === document.activeElement) {
                    ev.detail?.proms?.push(this.props.updateProperty({ target: el }));
                }
            };
            useBus(this.props.record.model.bus, ModelEvent.NEED_LOCAL_CHANGES, flush);
            useBus(this.props.record.model.bus, ModelEvent.WILL_SAVE_URGENTLY, flush);
        }
    }
}
