// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/google_slide_viewer/google_slide_viewer */

import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { CharField, charField } from "@web/fields/basic/char/char_field";

/**
 * @param {string | false} value
 * @param {string | number} page
 */
export function getGoogleSlideUrl(value, page) {
    /** @type {string | false} */
    let url = false;
    const googleRegExp =
        /(^https:\/\/docs\.google\.com).*(\/d\/e\/|\/d\/)([A-Za-z0-9-_]+)/;
    const google = /** @type {string} */ (value).match(googleRegExp);
    if (google && google[3]) {
        url = `https://docs.google.com/presentation${google[2]}${google[3]}/preview?slide=${encodeURIComponent(page)}`;
    }
    return url;
}

export class GoogleSlideViewer extends CharField {
    static template = "web.GoogleSlideViewer";
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;

    setup() {
        super.setup();
        this.notification = useService("notification");
        this.page = 1;
    }

    _get_slide_page() {
        return this.props.record.data[this.props.name + "_page"]
            ? this.props.record.data[this.props.name + "_page"]
            : this.page;
    }

    get url() {
        const value = this.props.record.data[this.props.name];
        return value ? getGoogleSlideUrl(value, this._get_slide_page()) : false;
    }

    onLoadFailed() {
        this.notification.add(_t("Could not display the selected slide"), {
            type: "danger",
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const googleSlideViewer = {
    ...charField,
    component: GoogleSlideViewer,
    displayName: _t("Google Slide Viewer"),
    // See the same declaration on `pdf_viewer`: `<name>_page` was read out of
    // `record.data` without being declared, so it was never loaded and the
    // viewer always opened on the first slide.
    fieldDependencies: ({ name }) => [
        { name: `${name}_page`, optional: true, readonly: true },
    ],
};

registerField("google_slide_viewer", googleSlideViewer);
