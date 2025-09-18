// @ts-check

/** @module @web/core/tree/in_range_options - Date range option labels for "in range" virtual operator */

import { _t } from "@web/core/l10n/translation";

/** @type {Array<[string, import("@web/core/l10n/translation").LazyTranslatedString]>} */
export const IN_RANGE_OPTIONS = [
    ["today", _t("Today")],
    ["last 7 days", _t("Last 7 days")],
    ["last 30 days", _t("Last 30 days")],
    ["month to date", _t("Month to date")],
    ["last month", _t("Last month")],
    ["year to date", _t("Year to date")],
    ["last 12 months", _t("Last 12 months")],
    ["custom range", _t("Custom range")],
];
