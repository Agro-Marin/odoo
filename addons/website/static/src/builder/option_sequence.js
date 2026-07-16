/** @odoo-module native */
import {
    ANIMATE,
    END,
    LAYOUT_COLUMN,
    SNIPPET_SPECIFIC_AFTER,
    SNIPPET_SPECIFIC_END,
    SNIPPET_SPECIFIC_NEXT,
    splitBetween,
    VERTICAL_ALIGNMENT,
} from "@html_builder/utils/option_sequence";

// Gives names to website options sequence.
const [LAYOUT, ...__DETECT_ERROR_WEBSITE_0__] = splitBetween(
    SNIPPET_SPECIFIC_AFTER,
    LAYOUT_COLUMN,
    1,
);
if (__DETECT_ERROR_WEBSITE_0__.length > 0) {
    console.error("Wrong count in website split after specific");
}
const [WEBSITE_BACKGROUND_OPTIONS, BOX_BORDER_SHADOW, ...__DETECT_ERROR_WEBSITE_1__] =
    splitBetween(VERTICAL_ALIGNMENT, SNIPPET_SPECIFIC_NEXT, 2);
if (__DETECT_ERROR_WEBSITE_1__.length > 0) {
    console.error("Wrong count in website split after vertical alignment");
}
const [LAYOUT_GRID, ...__DETECT_ERROR_WEBSITE_2__] = splitBetween(
    LAYOUT_COLUMN,
    VERTICAL_ALIGNMENT,
    1,
);
if (__DETECT_ERROR_WEBSITE_2__.length > 0) {
    console.error("Wrong count in website split after column layout");
}
const [GRID_COLUMNS, ...__DETECT_ERROR_WEBSITE_3__] = splitBetween(
    VERTICAL_ALIGNMENT,
    SNIPPET_SPECIFIC_NEXT,
    1,
);
if (__DETECT_ERROR_WEBSITE_3__.length > 0) {
    console.error("Wrong count in website split after vertical alignment");
}
const [
    COVER_PROPERTIES,
    CONTAINER_WIDTH,
    SCROLL_BUTTON,
    ...__DETECT_ERROR_WEBSITE_4__
] = splitBetween(SNIPPET_SPECIFIC_NEXT, SNIPPET_SPECIFIC_END, 3);
if (__DETECT_ERROR_WEBSITE_4__.length > 0) {
    console.error("Wrong count in website split before specific end");
}

const [GRID_IMAGE, TEXT_HIGHLIGHT, ...__DETECT_ERROR_WEBSITE_5__] = splitBetween(
    SNIPPET_SPECIFIC_END,
    ANIMATE,
    2,
);
if (__DETECT_ERROR_WEBSITE_5__.length > 0) {
    console.error("Wrong count in website split before animate");
}

const [CONDITIONAL_VISIBILITY, DEVICE_VISIBILITY, ...__DETECT_ERROR_WEBSITE_6__] =
    splitBetween(ANIMATE, END, 2);
if (__DETECT_ERROR_WEBSITE_6__.length > 0) {
    console.error("Wrong count in website split after animate");
}
export {
    BOX_BORDER_SHADOW,
    CONDITIONAL_VISIBILITY,
    CONTAINER_WIDTH,
    COVER_PROPERTIES,
    DEVICE_VISIBILITY,
    GRID_COLUMNS,
    GRID_IMAGE,
    LAYOUT,
    LAYOUT_COLUMN,
    LAYOUT_GRID,
    SCROLL_BUTTON,
    TEXT_HIGHLIGHT,
    WEBSITE_BACKGROUND_OPTIONS,
};
