// @ts-check
/** @odoo-module native */

/** @module @web/views/widgets/widget - Generic widget component resolving view_widgets registry entries with props extraction and validation */

import { Component, xml } from "@odoo/owl";
import { evaluateBooleanExpr, evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
const viewWidgetRegistry = registry.category("view_widgets");

// The per-element shape must live under `element`, not as a sibling `shape`:
// OWL's array validator reads `element` and ignores a sibling `shape`, so the
// previous placement left the element shape completely unenforced. Enforce the
// two load-bearing fields (name, type) and forward the rest via `"*": true`
// (label / availableTypes / default / help / choices) so a well-formed
// registration with extra descriptive fields still validates.
const supportedInfoValidation = {
    type: Array,
    element: {
        type: Object,
        shape: {
            name: String,
            type: String,
            "*": true,
        },
    },
    optional: true,
};

viewWidgetRegistry.addValidation({
    component: { validate: (c) => c.prototype instanceof Component },
    extractProps: { type: Function, optional: true },
    additionalClasses: { type: Array, element: String, optional: true },
    fieldDependencies: {
        type: [
            Function,
            {
                type: Array,
                element: Object,
                shape: { name: String, type: String },
            },
        ],
        optional: true,
    },
    listViewWidth: {
        type: [
            Number,
            {
                type: Array,
                element: Number,
                validate: (array) => array.length === 1 || array.length === 2,
            },
            Function,
        ],
        optional: true,
    },
    supportedAttributes: supportedInfoValidation,
    supportedOptions: supportedInfoValidation,
});

/**
 * Generic wrapper that renders `<widget />` tags in view archs by looking up
 * the named component from the "view_widgets" registry and forwarding
 * extracted props, readonly state, and the current record.
 */
export class Widget extends Component {
    static template = xml /*xml*/ `
        <div t-att-class="classNames" t-att-style="props.style">
            <t t-component="widget.component" t-props="widgetProps" />
        </div>`;

    /**
     * Parse a `<widget>` XML node into a descriptor with name, options, and attributes.
     * @param {Element} node - arch XML element
     * @returns {{ name: string, widget: Object, options: Object, attrs: Object }}
     */
    static parseWidgetNode = function (node) {
        const name = /** @type {string} */ (node.getAttribute("name"));
        const widget = viewWidgetRegistry.get(name);
        const widgetInfo = {
            name,
            widget,
            options: {},
            attrs: {},
        };

        for (const { name, value } of node.attributes) {
            if (["name", "widget"].includes(name)) {
                // avoid adding name and widget to attrs
                continue;
            }
            if (name === "options") {
                widgetInfo.options = evaluateExpr(value);
            } else if (!name.startsWith("t-att")) {
                // all other (non dynamic) attributes
                widgetInfo.attrs[name] = value;
            }
        }

        return widgetInfo;
    };
    static props = {
        "*": true,
    };

    setup() {
        if (this.props.widgetInfo) {
            this.widget = this.props.widgetInfo.widget;
        } else {
            this.widget = viewWidgetRegistry.get(this.props.name);
        }
    }

    /** @returns {Record<string, boolean>} CSS class map including o_widget, widget-specific, and additional classes */
    get classNames() {
        const classNames = {
            o_widget: true,
            [`o_widget_${this.props.name}`]: true,
            [this.props.className]: Boolean(this.props.className),
        };
        if (this.widget.additionalClasses) {
            for (const cls of this.widget.additionalClasses) {
                classNames[cls] = true;
            }
        }
        return classNames;
    }
    /** @returns {Object} merged props for the inner widget component (record, readonly, and extracted arch props) */
    get widgetProps() {
        const record = this.props.record;

        let readonlyFromModifiers = false;
        let propsFromNode = {};
        if (this.props.widgetInfo) {
            const widgetInfo = this.props.widgetInfo;
            readonlyFromModifiers = evaluateBooleanExpr(
                widgetInfo.attrs.readonly,
                record.evalContextWithVirtualIds,
            );
            const dynamicInfo = {
                readonly: readonlyFromModifiers,
            };
            propsFromNode = this.widget.extractProps
                ? this.widget.extractProps(widgetInfo, dynamicInfo)
                : {};
        }
        return {
            record,
            readonly: !record.isInEdition || readonlyFromModifiers || false,
            ...propsFromNode,
        };
    }
}
