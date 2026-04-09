/** @odoo-module native */
import {
    textInputBasePassthroughProps,
} from "@html_builder/core/building_blocks/builder_text_input_base";
import { BuilderUrlPicker } from "@html_builder/core/building_blocks/builder_urlpicker";
import {
    basicContainerBuilderComponentProps,
    useActionInfo,
} from "@html_builder/core/utils";
import { AutoComplete } from "@web/components/autocomplete/autocomplete";
import { _t } from "@web/core/l10n/translation";
import { useChildRef } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import wUtils from "@website/js/utils";

/**
 * AutoComplete subclass for use within the BuilderUrlPicker.
 *
 * Overrides the root CSS class so that the autocomplete dropdown
 * renders correctly inside the builder sidebar.
 */
export class AutoCompleteBuilderUrlPicker extends AutoComplete {
    static template = "website.AutoCompleteBuilderUrlPicker";
    static props = {
        ...AutoComplete.props,
    };

    get autoCompleteRootClass() {
        return `${super.autoCompleteRootClass} w-100`;
    }
}

patch(BuilderUrlPicker, {
    components: { ...BuilderUrlPicker.components, AutoCompleteBuilderUrlPicker },
});

patch(BuilderUrlPicker.prototype, {
    setup() {
        super.setup();
        this.autocompleteRef = useChildRef();
        const actionInfo = useActionInfo();
        this.body = actionInfo.editingDocument.body;
    },

    get sources() {
        return [
            {
                placeholder: _t("Loading..."),
                options: (term) =>
                    wUtils.loadOptionsSource(term, this.body, this.onSelect.bind(this)),
                optionSlot: "urlOption",
            },
        ];
    },

    onSelect(value) {
        this.autocompleteRef.el.querySelector("input").value = value;
        this.commit(value);
    },

    onChange({ inputValue, isOptionSelected }) {
        if (!isOptionSelected) {
            this.commit(inputValue);
        }
    },

    openPreviewUrl() {
        const input = this.autocompleteRef.el?.querySelector("input");
        if (input?.value) {
            window.open(input.value, "_blank");
        }
    },
});
