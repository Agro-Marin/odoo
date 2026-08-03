/** @odoo-module native */
import { Component, onMounted, useRef, useSubEnv, xml } from "@odoo/owl";
import { Dropdown, useDropdownState } from "@web/components/dropdown";
import { _t } from "@web/core/translation";
import { setElementContent } from "@web/core/utils/dom/html";

import {
    basicContainerBuilderComponentProps,
    useApplyVisibility,
    useSelectableComponent,
    useVisibilityObserver,
} from "../utils.js";
import { BuilderComponent } from "./builder_component.js";

export class WithIgnoreItem extends Component {
    static template = xml`<t t-slot="default"/>`;
    static props = {
        slots: { type: Object },
    };
    setup() {
        useSubEnv({
            ignoreBuilderItem: true,
        });
    }
}

export class BuilderSelect extends Component {
    static template = "html_builder.BuilderSelect";
    static props = {
        ...basicContainerBuilderComponentProps,
        className: { type: String, optional: true },
        dropdownContainerClass: { type: String, optional: true },
        disabled: { type: Boolean, optional: true },
        slots: {
            type: Object,
            shape: {
                default: Object, // Content is not optional
                fixedButton: { type: Object, optional: true },
            },
        },
        dropdownClass: { type: String, optional: true },
    };
    static defaultProps = { dropdownClass: "o-hb-select-dropdown" };
    static components = {
        Dropdown,
        BuilderComponent,
        WithIgnoreItem,
    };

    setup() {
        useVisibilityObserver("content", useApplyVisibility("root"));

        this.dropdown = useDropdownState();

        const buttonRef = useRef("button");
        let currentLabel;
        const updateCurrentLabel = () => {
            if (!this.props.slots.fixedButton) {
                const newHtml = currentLabel || _t("None");
                if (buttonRef.el && buttonRef.el.innerHTML !== newHtml) {
                    setElementContent(buttonRef.el, newHtml);
                }
            }
        };
        useSelectableComponent(this.props.id, {
            onItemChange(item) {
                currentLabel = item.getLabel();
                updateCurrentLabel();
            },
        });
        onMounted(updateCurrentLabel);
        useSubEnv({
            onSelectItem: () => {
                this.dropdown.close();
            },
        });
    }
}
