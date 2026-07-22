/**
 * Helpers for tests whose expectations depend on font metrics.
 *
 * `ListPlugin.adjustListPadding` derives `padding-inline-start` from exactly two
 * environment-dependent inputs, and they need different pins:
 *
 *  1. `measureMarkerWidth(li)` -- the `::marker` width, decided by the browser's
 *     font rasterizer. Reproducing it across machines needs the *family* pinned
 *     ({@link pinFont}), and even then the metrics can shift between browser
 *     versions. A test asserting a padding it did not stub must therefore also
 *     carry `test.tags("font-dependent")`.
 *  2. `defaultPadding = 2 * root font-size` -- the threshold the marker padding
 *     must exceed. This one is pure arithmetic over a value CSS fully controls,
 *     so {@link pinRootFontSize} is enough.
 *
 * Tests that stub input 1 (`pinMarkerWidth` in `list_font_size.test.js`) only
 * need input 2 pinned: the family cannot influence a measurement that is no
 * longer taken, and such tests are NOT font-dependent.
 *
 * /!\ Pinning with `:root { font: ... }` alone does NOT pin input 1. The web
 * client sets `font-family` on the editable itself (Inter since 19.0), and a
 * declaration applied directly to an element always beats a value inherited
 * from an ancestor, regardless of specificity. The pin must therefore target
 * the editable and its descendants -- which is what {@link pinFont} does.
 * (This is why `ol { font: ... }`-style pins work while `:root` ones silently
 * do not: they apply to the measured element rather than to an ancestor.)
 */

export const TEST_FONT_FAMILY = "Roboto";
const TEST_FONT_URL = "/web/static/fonts/google/Roboto/Roboto-Regular.ttf";

/**
 * Load the pinned font and register it on the document. Call from `before`.
 */
export async function loadTestFont() {
    const font = new FontFace(TEST_FONT_FAMILY, `url(${TEST_FONT_URL})`);
    await font.load();
    document.fonts.add(font);
    await document.fonts.ready;
}

/**
 * `styleContent` that pins the root font-size, from which `adjustListPadding`
 * derives its default padding (`2 * root font-size`).
 *
 * This is the only pin a test needs when it stubs the marker measurement.
 * Without it the threshold silently follows the host's default root font-size.
 *
 * @param {string} [size="14px"] root font-size
 * @returns {string}
 */
export function pinRootFontSize(size = "14px") {
    return `:root { font-size: ${size}; }`;
}

/**
 * `styleContent` that additionally pins the font used to lay out the editable,
 * so `::marker` measurements are as reproducible as the rasterizer allows.
 *
 * Only for tests that genuinely measure a marker. If the test stubs
 * `measureMarkerWidth`, use {@link pinRootFontSize} instead -- the family is
 * then inert, and keeping it here would imply a dependency that no longer
 * exists.
 *
 * @param {string} [size="14px"] root font-size
 * @returns {string}
 */
export function pinFont(size = "14px") {
    return (
        `${pinRootFontSize(size)} ` +
        `.odoo-editor-editable, .odoo-editor-editable * { font-family: ${TEST_FONT_FAMILY}; }`
    );
}
