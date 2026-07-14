/** @odoo-module native */

/**
 * Inserts `text` at the composer's current selection, in whichever edit mode
 * the composer currently is:
 *
 * - HTML mode (`editor` given): insert through the editor and record a
 *   history step;
 * - plain-text mode: splice `composer.composerText` around the current
 *   selection and report the resulting cursor position through `moveCursor`
 *   (typically `useSelection().moveCursor`, which also synchronizes the DOM
 *   selection of the textarea).
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
