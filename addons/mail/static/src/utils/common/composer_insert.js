/** @odoo-module native */

/**
 * Inserts `text` at the composer's current selection: through the editor (plus
 * a history step) in HTML mode, or by splicing `composer.composerText` and
 * reporting the cursor position through `moveCursor` in plain-text mode.
 *
 * @param {import("models").Composer} composer
 * @param {string} text
 * @param {Object} [options]
 * @param {import("@html_editor/editor").Editor} [options.editor]
 * @param {(position: number) => void} [options.moveCursor]
 */
export function insertAtSelection(composer, text, { editor, moveCursor } = {}) {
    if (editor) {
        editor.shared.dom.insert(text);
        editor.shared.history.addStep();
        return;
    }
    const composerText = composer.composerText;
    const firstPart = composerText.slice(0, composer.selection.start);
    const secondPart = composerText.slice(composer.selection.end, composerText.length);
    composer.composerText = firstPart + text + secondPart;
    moveCursor?.((firstPart + text).length);
}
