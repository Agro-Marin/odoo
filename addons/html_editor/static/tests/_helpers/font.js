import { ListPlugin } from "@html_editor/main/list/list_plugin";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

export const TEST_FONT_FAMILY = "Roboto";
const TEST_FONT_URL = "/web/static/fonts/google/Roboto/Roboto-Regular.ttf";

export async function loadTestFont() {
    const font = new FontFace(TEST_FONT_FAMILY, `url(${TEST_FONT_URL})`);
    await font.load();
    document.fonts.add(font);
    await document.fonts.ready;
}

/**
 * @param {string} [size="14px"]
 * @returns {string}
 */
export function pinRootFontSize(size = "14px") {
    return `:root { font-size: ${size}; }`;
}

/**
 * @param {string} [size="14px"]
 * @returns {string}
 */
export function pinFont(size = "14px") {
    return (
        `${pinRootFontSize(size)} ` +
        `.odoo-editor-editable, .odoo-editor-editable * { font-family: ${TEST_FONT_FAMILY}; }`
    );
}

/**
 * @param {number} width
 */
export function pinMarkerWidth(width) {
    patchWithCleanup(ListPlugin.prototype, {
        measureMarkerWidth() {
            return width;
        },
    });
}
