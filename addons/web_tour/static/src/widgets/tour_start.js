/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { CharField, charField } from "@web/fields/basic/char/char_field";

export class TourStartWidget extends CharField {
    static template = "web_tour.TourStartWidget";
    static props = {
        ...CharField.props,
        link: { type: Boolean, optional: true },
    };

    setup() {
        this.tour = useService("tour_service");
    }

    get tourData() {
        return this.props.record.data;
    }

    _onStartTour() {
        this.tour.startTour(this.tourData.name, {
            mode: "manual",
            url: this.tourData.url,
            fromDB: this.tourData.custom,
            rainbowManMessage: this.tourData.rainbow_man_message,
        });
    }

    _onTestTour() {
        this.tour.startTour(this.tourData.name, {
            mode: "auto",
            url: this.tourData.url,
            fromDB: this.tourData.custom,
            showPointerDuration: 250,
            rainbowManMessage: this.tourData.rainbow_man_message,
        });
    }
}

export const tourStartWidgetField = {
    ...charField,
    component: TourStartWidget,
    // Not `charField`'s list: `extractProps` is replaced rather than extended,
    // so none of the char options are read here and declaring them would offer
    // Studio settings that do nothing.
    supportedOptions: [
        {
            label: _t("Link"),
            name: "link",
            type: "boolean",
            help: _t("Show the tour name as a link that starts it, not as text."),
        },
    ],
    extractProps: ({ options }) => ({
        link: options.link,
    }),
};

registry.category("fields").add("tour_start_widget", tourStartWidgetField);
