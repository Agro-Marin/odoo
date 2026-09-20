/** @odoo-module native */
import { SURVEY_CHART_COLORS } from "@web/core/colors/colors";
import { colorToRgb } from "@web/core/utils/format/colors";

// Keep the RGB-triplet export consumed by survey session interactions.
export default SURVEY_CHART_COLORS.map((color) =>
    colorToRgb(color).replaceAll(" ", ""),
);
