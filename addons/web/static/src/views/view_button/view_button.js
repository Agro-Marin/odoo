// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { useDropdownCloser } from "@web/components/dropdown/dropdown_hook";
import { sharedComponents } from "@web/core/shared_components";
import { pick } from "@web/core/utils/collections/objects";
import { debounce as debounceFn } from "@web/core/utils/timing";
const explicitRankClasses = [
    "btn-primary",
    "btn-secondary",
    "btn-link",
    "btn-success",
    "btn-info",
    "btn-warning",
    "btn-danger",
];

/** @type {Record<string, string>} */
const odooToBootstrapClasses = {
    oe_highlight: "btn-primary",
    oe_link: "btn-link",
};

/**
 * @param {string} iconString
 * @returns {{ tag: string, class?: string, src?: string }}
 */
function iconFromString(iconString) {
    const icon = {};
    if (
        iconString.startsWith("fa-solid ") ||
        iconString.startsWith("fa-regular ") ||
        iconString.startsWith("fa-brands ")
    ) {
        icon.tag = "i";
        icon.class = `o_button_icon ${iconString}`;
    } else if (iconString.startsWith("fa-")) {
        icon.tag = "i";
        if (iconString.endsWith("-o")) {
            icon.class = `o_button_icon fa-regular ${iconString.slice(0, -2)}`;
        } else {
            icon.class = `o_button_icon fa-solid ${iconString}`;
        }
    } else if (iconString.startsWith("oi-")) {
        icon.tag = "i";
        icon.class = `o_button_icon oi oi-fw ${iconString}`;
    } else {
        icon.tag = "img";
        icon.src = iconString;
    }
    return icon;
}

export class ViewButton extends Component {
    static template = "web.views.ViewButton";
    static props = {
        id: { type: [String, Number], optional: true },
        tag: { type: String, optional: true },
        record: { type: Object, optional: true },
        attrs: { type: Object, optional: true },
        modifiers: { type: Object, optional: true },
        className: { type: String, optional: true },
        context: { type: [Object, String], optional: true },
        clickParams: { type: Object, optional: true },
        icon: { type: [String, Boolean], optional: true },
        defaultRank: { type: String, optional: true },
        disabled: { type: Boolean, optional: true },
        size: { type: String, optional: true },
        tabindex: { type: [String, Number], optional: true },
        title: { type: String, optional: true },
        style: { type: String, optional: true },
        string: { type: String, optional: true },
        slots: { type: Object, optional: true },
        onClick: { type: Function, optional: true },
    };
    static defaultProps = {
        tag: "button",
        className: "",
        clickParams: {},
        attrs: {},
        modifiers: {},
    };

    /** @type {any} */
    dropdownControl;

    setup() {
        if (this.props.icon) {
            this.icon = iconFromString(this.props.icon);
        }
        const { debounce } = this.clickParams;
        if (debounce) {
            this.onClick = debounceFn(this.onClick.bind(this), debounce, true);
        }
        this.dropdownControl = useDropdownCloser();
    }

    get clickParams() {
        return { context: this.props.context, ...this.props.clickParams };
    }

    get hasBigTooltip() {
        return Boolean(odoo.debug) || this.clickParams.help;
    }

    get hasSmallToolTip() {
        return !this.hasBigTooltip && this.props.title;
    }

    /**
     * @returns {string}
     */
    get tooltip() {
        return JSON.stringify({
            debug: Boolean(odoo.debug),
            button: {
                string: this.props.string,
                help: this.clickParams.help,
                context: this.clickParams.context,
                invisible: this.props.modifiers.invisible,
                column_invisible: this.props.modifiers.column_invisible,
                readonly: this.props.modifiers.readonly,
                required: this.props.modifiers.required,
                special: this.clickParams.special,
                type: this.clickParams.type,
                name: this.clickParams.name,
                title: this.props.title,
            },
            context: this.props.record && this.props.record.context,
            model: this.props.record && this.props.record.resModel,
        });
    }

    get disabled() {
        const { name, type, special } = this.clickParams;
        return (!name && !type && !special) || this.props.disabled;
    }

    /**
     * @param {MouseEvent} ev
     * @param {boolean} [newWindow]
     */
    onClick(ev, newWindow) {
        if (this.props.tag === "a") {
            ev.preventDefault();
        }

        if (this.props.onClick) {
            return this.props.onClick();
        }

        return this.execute(newWindow);
    }

    /**
     * @param {boolean} [newWindow]
     * @returns {any}
     */
    execute(newWindow) {
        return this.env.onClickViewButton({
            clickParams: this.clickParams,
            getResParams: () =>
                pick(
                    this.props.record || {},
                    "context",
                    "evalContext",
                    "resModel",
                    "resId",
                    "resIds",
                ),
            beforeExecute: () => this.dropdownControl.close(),
            newWindow,
        });
    }

    /**
     * @returns {string}
     */
    getClassName() {
        const classNames = [];
        let hasExplicitRank = false;
        if (this.props.className) {
            for (let cls of this.props.className.split(" ")) {
                if (cls in odooToBootstrapClasses) {
                    cls = odooToBootstrapClasses[cls];
                }
                classNames.push(cls);
                if (!hasExplicitRank && explicitRankClasses.includes(cls)) {
                    hasExplicitRank = true;
                }
            }
        }
        if (this.props.tag === "button") {
            const hasOtherClasses = classNames.length;
            classNames.unshift("btn");
            if ((!hasExplicitRank && this.props.defaultRank) || !hasOtherClasses) {
                classNames.push(this.props.defaultRank || "btn-secondary");
            }
            if (this.props.size) {
                classNames.push(`btn-${this.props.size}`);
            }
        }
        return classNames.join(" ");
    }
}

sharedComponents.add("ViewButton", ViewButton);
