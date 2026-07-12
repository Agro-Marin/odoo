// @ts-check
/** @odoo-module native */

/** @module @web/fields/temporal/timezone_mismatch/timezone_mismatch_field - Timezone selection field that warns when browser and user timezones differ */

import { formatDateTime } from "@web/core/l10n/dates";
import { DateTime } from "@web/core/l10n/luxon";
import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import {
    SelectionField,
    selectionField,
} from "@web/fields/selection/selection/selection_field";

export class TimezoneMismatchField extends SelectionField {
    static template = "web.TimezoneMismatchField";
    static props = {
        ...super.props,
        tzOffsetField: { type: String, optional: true },
        mismatchTitle: { type: String, optional: true },
    };
    static defaultProps = {
        ...super.defaultProps,
        tzOffsetField: "tz_offset",
        mismatchTitle: _t(
            "Timezone Mismatch : This timezone is different from that of your browser.\nPlease, set the same timezone as your browser's to avoid time discrepancies in your system.",
        ),
    };

    /** @returns {boolean} Whether the user's timezone offset differs from the browser's */
    get mismatch() {
        const userOffset = this.props.record.data[this.props.tzOffsetField];
        if (userOffset && this.props.record.data[this.props.name]) {
            const offset = -new Date().getTimezoneOffset();
            let browserOffset = offset < 0 ? "-" : "+";
            browserOffset += Math.floor(Math.abs(offset / 60))
                .toFixed(0)
                .padStart(2, "0");
            browserOffset += Math.abs(offset % 60)
                .toFixed(0)
                .padStart(2, "0");
            return browserOffset !== userOffset;
        } else if (!this.props.record.data[this.props.name]) {
            return true;
        }
        return false;
    }
    /** @returns {string} Warning message for the timezone mismatch tooltip */
    get mismatchTitle() {
        if (!this.props.record.data[this.props.name]) {
            return _t("Set a timezone on your user");
        }
        return this.props.mismatchTitle;
    }
    /** @returns {Array<[string, string]>} Selection options with local time appended on mismatch */
    get options() {
        if (!this.mismatch) {
            return super.options;
        }
        return super.options.map((option) => {
            const [value, label] = option;
            if (value === this.props.record.data[this.props.name]) {
                const offset = this.props.record.data[this.props.tzOffsetField].match(
                    /([+-])([0-9]{2})([0-9]{2})/,
                );
                const sign = offset[1] === "-" ? -1 : 1;
                const userOffset =
                    sign *
                    (Number.parseInt(offset[2], 10) * 60 +
                        Number.parseInt(offset[3], 10));
                const browserOffset = -new Date().getTimezoneOffset();
                // UTC time of the user's selected timezone, e.g. UTC 00:00 with
                // userOffset +0300 and browserOffset +0200 gives 01:00.
                const userUTCDatetime = DateTime.utc().plus({
                    minutes: userOffset - browserOffset,
                });
                return [value, `${label} (${formatDateTime(userUTCDatetime)})`];
            }
            return [value, label];
        });
    }
}

export const timezoneMismatchField = {
    ...selectionField,
    component: TimezoneMismatchField,
    additionalClasses: ["d-flex"],
    supportedOptions: [
        ...(selectionField.supportedOptions || []),
        {
            label: _t("Mismatch title"),
            name: "mismatch_title",
            type: "string",
        },
        {
            label: _t("Timezone offset field"),
            name: "tz_offset_field",
            type: "field",
            availableTypes: ["char"],
        },
    ],
    extractProps({ options }) {
        const props = selectionField.extractProps(...arguments);
        props.tzOffsetField = options.tz_offset_field;
        props.mismatchTitle = options.mismatch_title;
        return props;
    },
    // The mismatch computation reads the tz-offset field; declare it as a
    // dependency so the model fetches it even when the arch omits it (otherwise
    // `record.data[tzOffsetField]` is undefined and the warning degrades
    // silently).
    fieldDependencies: ({ options }) => [
        { name: options.tz_offset_field || "tz_offset", type: "char" },
    ],
};

registerField("timezone_mismatch", timezoneMismatchField);
