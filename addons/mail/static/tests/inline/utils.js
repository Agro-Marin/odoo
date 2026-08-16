import {
    TABLE_ATTRIBUTES,
    TABLE_STYLES,
} from "@mail/views/web/fields/html_mail_field/convert_inline";

const tableAttributesString = Object.keys(TABLE_ATTRIBUTES)
    .map((key) => `${key}="${TABLE_ATTRIBUTES[key]}"`)
    .join(" ");
const tableStylesString = Object.keys(TABLE_STYLES)
    .map((key) => `${key}: ${TABLE_STYLES[key]};`)
    .join(" ");
/**
 * @param {Array<Array<Number|null>>} matrix
 * @returns {string}
 */
export function getGridHtml(matrix) {
    return (
        `<div class="container">` +
        matrix
            .map(
                (row, iRow) =>
                    `<div class="row">` +
                    row
                        .map(
                            (col, iCol) =>
                                `<div class="${
                                    col ? "col-" + col : "col"
                                }">(${iRow}, ${iCol})</div>`,
                        )
                        .join("") +
                    `</div>`,
            )
            .join("") +
        `</div>`
    );
}
export function getTdHtml(colspan, text, containerWidth) {
    const style = containerWidth
        ? ` style="max-width: ${Math.round(((containerWidth * colspan) / 12) * 100) / 100}px;"`
        : "";
    return `<td colspan="${colspan}"${style}>${text}</td>`;
}
/**
 * @param {Array<Array<Array<[Number, Number, string?, number?]>>>} matrix
 * @param {Number} [containerWidth]
 * @returns {string}
 */
export function getTableHtml(matrix, containerWidth) {
    return (
        `<table ${tableAttributesString} style="width: 100% !important; ${tableStylesString}">` +
        matrix
            .map(
                (row, iRow) =>
                    `<tr>` +
                    row
                        .map((col, iCol) =>
                            getTdHtml(
                                col[0],
                                typeof col[2] === "string"
                                    ? col[2]
                                    : `(${iRow}, ${iCol})`,
                                containerWidth,
                            ),
                        )
                        .join("") +
                    `</tr>`,
            )
            .join("") +
        `</table>`
    );
}
/**
 * @param {Number} nRows
 * @param {Number|Number[]} nCols
 * @returns {string}
 */
export function getRegularGridHtml(nRows, nCols) {
    const matrix = new Array(nRows)
        .fill()
        .map((_, iRow) => new Array(Array.isArray(nCols) ? nCols[iRow] : nCols).fill());
    return getGridHtml(matrix);
}
/**
 * @param {Number} nRows
 * @param {Number|Number[]} nCols
 * @param {Number|Number[]} colspan
 * @param {Number|Number[]} width
 * @param {Number} containerWidth
 * @returns {string}
 */
export function getRegularTableHtml(nRows, nCols, colspan, width, containerWidth) {
    const matrix = new Array(nRows)
        .fill()
        .map((_, iRow) =>
            new Array(Array.isArray(nCols) ? nCols[iRow] : nCols)
                .fill()
                .map(() => [
                    Array.isArray(colspan) ? colspan[iRow] : colspan,
                    Array.isArray(width) ? width[iRow] : width,
                ]),
        );
    return getTableHtml(matrix, containerWidth);
}
