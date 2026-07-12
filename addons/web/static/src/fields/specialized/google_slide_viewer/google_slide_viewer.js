// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/google_slide_viewer/google_slide_viewer - Embedded Google Slides presentation viewer field */

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { CharField, charField } from "@web/fields/basic/char/char_field";

export function getGoogleSlideUrl(value, page) {
    /** @type {string | false} */
    let url = false;
    const googleRegExp =
        /(^https:\/\/docs\.google\.com).*(\/d\/e\/|\/d\/)([A-Za-z0-9-_]+)/;
    const google = value.match(googleRegExp);
    if (google && google[3]) {
        url = `https://docs.google.com/presentation${google[2]}${google[3]}/preview?slide=${encodeURIComponent(page)}`;
    }
    return url;
}

export class GoogleSlideViewer extends CharField {
    static template = "web.GoogleSlideViewer";
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

export const googleSlideViewer = {
    ...charField,
    component: GoogleSlideViewer,
    displayName: _t("Google Slide Viewer"),
};

registerField("google_slide_viewer", googleSlideViewer);
