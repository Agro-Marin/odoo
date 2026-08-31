/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";

export class DateTimeFieldOption extends BaseOptionComponent {
    static template = "html_builder.DateTimeFieldOption";
    static selector =
        "[data-oe-field][data-oe-type=date], [data-oe-field][data-oe-type=datetime]";

    setup() {
        super.setup();
        // The picker is a date one or a datetime one depending on the field it
        // edits, so the type has to follow the selected element.
        this.state = useDomState((editingElement) => ({
            fieldType: editingElement.dataset.oeType,
        }));
    }
}
