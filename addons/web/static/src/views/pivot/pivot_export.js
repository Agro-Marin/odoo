// @ts-check
/** @odoo-module native */

/**
 * @param {Object} header
 * @returns {{ title: string, width: number, height: number, is_bold: boolean }}
 */
function processHeader(header) {
    const inTotalColumn = header.groupId[1].length === 0;
    return {
        title: header.title,
        width: header.width,
        height: header.height,
        is_bold: !!header.measure && inTotalColumn,
    };
}

/**
 * @param {number} leafCount
 * @param {number} measureCount
 * @returns {number}
 */
export function computeExportedTableWidth(leafCount, measureCount) {
    const totalGroupWidth = leafCount > 1 ? measureCount : 0;
    return leafCount * measureCount + totalGroupWidth + 1;
}

/**
 * @param {Object} table
 * @param {Object} metaData
 * @param {string[]} metaData.activeMeasures
 * @param {string} metaData.resModel
 * @param {string} metaData.title
 * @returns {Object}
 */
export function formatPivotForExport(table, metaData) {
    const { headers } = table;

    let colGroupHeaderRows = headers.slice(0, -1);
    const measureRow = headers.at(-1).map(processHeader);

    colGroupHeaderRows[0].splice(0, 1);

    colGroupHeaderRows = colGroupHeaderRows.map((headerRow) =>
        headerRow.map(processHeader),
    );

    const tableRows = table.rows.map((row) => ({
        title: row.title,
        indent: row.indent,
        values: row.subGroupMeasurements.map((measurement) => {
            let value = measurement.value;
            if (value === undefined) {
                value = "";
            }
            return {
                is_bold: measurement.isBold,
                value,
            };
        }),
    }));

    return {
        model: metaData.resModel,
        title: metaData.title,
        col_group_headers: colGroupHeaderRows,
        measure_headers: measureRow,
        rows: tableRows,
        measure_count: metaData.activeMeasures.length,
    };
}
