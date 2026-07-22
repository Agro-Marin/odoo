/** @odoo-module native */
import { useOperation } from "@html_builder/core/operation_plugin";
import { BaseOptionComponent } from "@html_builder/core/utils";

export class FormOptionAddFieldButton extends BaseOptionComponent {
    static template = "website.s_website_form_form_option_add_field_button";
    static props = {
        addField: Function,
        tooltip: String,
    };

    setup() {
        // See GalleryElementOption: `BaseOptionComponent.setup` is what wires
        // the editor context and the builder components this template renders,
        // so an override must chain to it.
        super.setup();
        this.callOperation = useOperation();
    }

    addField() {
        this.callOperation(() => {
            this.props.addField(this.env.getEditingElement());
        });
    }
}
