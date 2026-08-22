// @ts-check
/** @odoo-module native */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { deepCopy } from "@web/core/utils/collections/objects";
import { useSortable } from "@web/core/utils/dnd/sortable_owl";
import { uuid } from "@web/core/utils/format/strings";
import { useService } from "@web/core/utils/hooks";
export class PropertyDefinitionSelection extends Component {
    static template = "web.PropertyDefinitionSelection";
    static props = {
        default: { type: String, optional: true },
        options: {},
        readonly: { type: Boolean, optional: true },
        canChangeDefinition: { type: Boolean, optional: true },
        onOptionsChange: { type: Function, optional: true },
        onDefaultOptionChange: { type: Function, optional: true },
    };

    setup() {
        this.notification = useService("notification");

        this.state = useState({
            newOption: null,
        });

        this.propertyDefinitionSelectionRef = useRef("propertyDefinitionSelection");
        this.addButtonRef = useRef("addButton");

        useEffect(() => {
            if (!this.state.newOption) {
                return;
            }
            const inputs = this.propertyDefinitionSelectionRef.el.querySelectorAll(
                ".o_field_property_selection_option input",
            );
            if (
                inputs &&
                inputs.length &&
                !(
                    /** @type {HTMLInputElement} */ (inputs[this.state.newOption.index])
                        .value
                )
            ) {
                inputs[this.state.newOption.index].focus();
            }
        });

        useSortable({
            enable: () => this.props.canChangeDefinition && !this.props.readonly,
            ref: this.propertyDefinitionSelectionRef,
            handle: ".o_field_property_selection_drag",
            elements: ".o_field_property_selection_option",
            cursor: "grabbing",
            onDrop: async ({ element, previous }) => {
                const movedOption = element.getAttribute("option-name");
                const destinationOption = previous?.getAttribute("option-name");
                await this.onOptionMoveTo(movedOption, destinationOption);
            },
        });
    }

    /**
     * @returns {array}
     */
    get options() {
        return deepCopy(this.props.options || []);
    }

    /**
     * @returns {array}
     */
    get optionsVisible() {
        const options = this.options || [];
        const newOption = this.state.newOption;
        if (newOption) {
            options.splice(newOption.index, 0, [newOption.name, ""]);
        }
        return options;
    }

    onOptionCreate(index) {
        this.state.newOption = {
            index: index,
            name: uuid(),
        };
    }

    /**
     * @param {Event} event
     * @param {number} optionIndex
     */
    onOptionChange(event, optionIndex) {
        const target = /** @type {HTMLInputElement} */ (event.target);
        const newLabel = target.value;

        if (this.options[optionIndex] && this.options[optionIndex][1] === newLabel) {
            return;
        }

        const options = this.optionsVisible;

        if (!newLabel || !newLabel.length) {
            options.splice(optionIndex, 1);
        } else {
            options[optionIndex][1] = newLabel;
        }

        const nonEmptyOptions = options.filter(
            (option) => option[1] && option[1].length,
        );
        this.props.onOptionsChange(nonEmptyOptions);

        if (this.state.newOption) {
            this.state.newOption = null;
        }
    }

    /**
     * @param {FocusEvent} event
     * @param {number} optionIndex
     */
    onOptionBlur(event, optionIndex) {
        const target = /** @type {HTMLInputElement} */ (event.target);
        if (target.value && target.value.length) {
            return;
        } else if (this._ignoreBlur) {
            this._ignoreBlur = false;
            return;
        }

        if (event.relatedTarget === this.addButtonRef.el) {
            event.stopPropagation();
            event.preventDefault();
        } else if (optionIndex === this.state.newOption?.index) {
            this.state.newOption = null;
        }
    }

    /**
     * @param {KeyboardEvent} event
     * @param {number} optionIndex
     */
    onOptionKeyDown(event, optionIndex) {
        if (event.key === "Enter") {
            const newLabel = /** @type {HTMLInputElement} */ (event.target).value;

            event.preventDefault();

            if (newLabel) {
                this.onOptionChange(event, optionIndex);
                this.onOptionCreate(optionIndex + 1);
            } else {
                event.stopPropagation();
            }
        } else if (["ArrowUp", "ArrowDown"].includes(event.key)) {
            event.stopPropagation();
            event.preventDefault();

            if (event.key === "ArrowUp" && optionIndex > 0) {
                const previousInput = /** @type {HTMLElement} */ (event.target)
                    .closest(".o_field_property_selection_option")
                    .previousElementSibling.querySelector("input");
                previousInput.focus();
            } else if (
                event.key === "ArrowDown" &&
                optionIndex < this.optionsVisible.length - 1
            ) {
                const nextInput = /** @type {HTMLElement} */ (event.target)
                    .closest(".o_field_property_selection_option")
                    .nextElementSibling.querySelector("input");
                nextInput.focus();
            }
        }
    }

    /**
     * @param {integer} optionIndex
     */
    onOptionSetDefault(optionIndex) {
        if (!this.props.canChangeDefinition) {
            return;
        }
        const newValue = this.optionsVisible[optionIndex][0];
        this.props.onDefaultOptionChange(
            newValue !== this.props.default ? newValue : false,
        );
    }

    /**
     * @param {integer} optionIndex
     */
    onOptionDelete(optionIndex) {
        const options = this.optionsVisible;
        options.splice(optionIndex, 1);
        const nonEmptyOptions = options.filter(
            (option) => option[1] && option[1].length,
        );
        this.props.onOptionsChange(nonEmptyOptions);
        if (this.state.newOption) {
            this.state.newOption = null;
        }
    }

    /**
     * @param {string} movedOption
     * @param {string} destinationOption
     */
    onOptionMoveTo(movedOption, destinationOption) {
        this._ignoreBlur = true;

        let options = this.optionsVisible;
        let destinationOptionIndex = options.findIndex(
            (option) => option[0] === destinationOption,
        );
        const movedOptionIndex = options.findIndex(
            (option) => option[0] === movedOption,
        );
        if (destinationOptionIndex < movedOptionIndex) {
            destinationOptionIndex++;
        }

        const activeEl = document.activeElement;
        if (
            activeEl &&
            this.propertyDefinitionSelectionRef.el.contains(activeEl) &&
            activeEl.tagName === "INPUT"
        ) {
            const optionName = activeEl
                .closest(".o_field_property_selection_option")
                .getAttribute("option-name");
            const editedOptionIndex = options.findIndex(
                (option) => option[0] === optionName,
            );
            options[editedOptionIndex][1] = /** @type {HTMLInputElement} */ (
                activeEl
            ).value;
        }

        options.splice(
            destinationOptionIndex,
            0,
            options.splice(movedOptionIndex, 1)[0],
        );

        if (this.state.newOption) {
            const newOptionIndex = options.findIndex(
                (option) => option[0] === this.state.newOption.name,
            );
            if (!options[newOptionIndex][1]?.length) {
                this.state.newOption = {
                    ...this.state.newOption,
                    index: newOptionIndex,
                };
                options = options.filter(
                    (option) => option[0] !== this.state.newOption.name,
                );
            } else {
                this.state.newOption = null;
            }
        }

        this.props.onOptionsChange(options);
    }
}
