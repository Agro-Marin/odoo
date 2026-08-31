/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";

export const DATE_TIME_FIELD_SELECTOR =
    "[data-oe-field][data-oe-type=date], [data-oe-field][data-oe-type=datetime]";

export class DateTimeFieldOption extends BaseOptionComponent {
    static template = "html_builder.DateTimeFieldOption";
    static selector = DATE_TIME_FIELD_SELECTOR;

    setup() {
        super.setup();
        // `date` and `datetime` share this option; the picker needs to know
        // which one it is editing to pick its format and granularity.
        this.state = useDomState((editingElement) => ({
            fieldType: editingElement.dataset.oeType,
        }));
    }
}
