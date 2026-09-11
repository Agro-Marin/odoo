/** @odoo-module native */
import { Component, useEffect, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { debounce } from "@web/core/utils/timing";
import { UrlField, urlField } from "@web/fields/basic/url/url_field";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { PageDependencies } from "@website/components/dialog/page_properties";

class PageUrlField extends UrlField {
    static components = { PageDependencies };
    static template = "website.PageUrlField";
    static defaultProps = {
        ...UrlField.defaultProps,
        websitePath: true,
    };

    setup() {
        super.setup();
        this.serverUrl = `${window.location.origin}/`;
        this.inputRef = useRef("input");

        useEffect(
            (inputEl) => {
                if (inputEl) {
                    const originalValue = inputEl.value;
                    let previousValueChanged = false;
                    const fireChangeEvent = debounce(() => {
                        const currentValue = inputEl.value;
                        const valueChanged = currentValue !== originalValue;
                        if (valueChanged !== previousValueChanged) {
                            if (currentValue[0] !== "/") {
                                inputEl.value = `/${currentValue}`;
                            }
                            inputEl.dispatchEvent(new Event("change"));
                            inputEl.value = currentValue;
                            previousValueChanged = valueChanged;
                        }
                    }, 100);

                    inputEl.addEventListener("input", fireChangeEvent);
                    return () => {
                        inputEl.removeEventListener("input", fireChangeEvent);
                    };
                }
            },
            () => [this.inputRef.el],
        );
    }

    get value() {
        let value = super.value;
        if (value[0] === "/") {
            value = value.substring(1);
        }
        this.props.record.data[this.props.name] = `/${value.trim()}`;
        return value;
    }
}

const pageUrlField = {
    ...urlField,
    component: PageUrlField,
};

registry.category("fields").add("page_url", pageUrlField);

export class ImageRadioField extends Component {
    static template = "website.FieldImageRadio";
    static props = {
        ...standardFieldProps,
        images: { type: Array, element: String },
    };

    setup() {
        const selection = this.props.record.fields[this.props.name].selection;
        this.values = selection
            .filter((item) => item[0] || item[1])
            .map((value, index) => [
                ...value,
                (this.props.images && this.props.images[index]) || "",
            ]);
    }

    /**
     * @param {String} value
     */
    onSelectValue(value) {
        this.props.record.update({ [this.props.name]: value });
    }
}

export const imageRadioField = {
    component: ImageRadioField,
    supportedOptions: [
        {
            label: _t("Images"),
            name: "images",
            type: "string",
            help: _t("Use an array to list the images to use in the radio selection."),
        },
    ],
    supportedTypes: ["selection"],
    extractProps: ({ options }) => ({
        images: options.images,
    }),
};

registry.category("fields").add("image_radio", imageRadioField);
