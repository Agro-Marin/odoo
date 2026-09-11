// @ts-check
/** @odoo-module native */

/**
 * @param {{composerText: string, selection: {start: number, end: number}}} composer
 * @param {string} text
 * @param {Object} [options]
 * @param {{shared: {dom: {insert(text: string): unknown}, history: {addStep(): unknown}}}} [options.editor]
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
