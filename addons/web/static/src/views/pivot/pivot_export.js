// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_export - Pure formatting of pivot table data for Excel/spreadsheet export */

/**
 * Format a single header cell for export.
 *
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
 * Number of columns the exported XLSX sheet contains.
 *
 * The export controller (/web/pivot/export_xlsx) writes, per data row: the
 * row title in column 0, then one value cell per entry of the measures row.
 * The measures row holds one cell per active measure for each leaf column
 * group, plus one cell per active measure for the "Total" column group —
 * the latter only when there is more than one leaf (see getTableHeaders).
 *
 * @param {number} leafCount - number of leaves of the column group tree
 * @param {number} measureCount - number of active measures
 * @returns {number}
 */
export function computeExportedTableWidth(leafCount, measureCount) {
    const totalGroupWidth = leafCount > 1 ? measureCount : 0;
    return leafCount * measureCount + totalGroupWidth + 1;
}

/**
 * Transform a pivot table (headers + rows) into a flat structure suitable
 * for encoding in Excel.
 *
 * @param {Object} table - Result of PivotModel.getTable()
 * @param {Object} metaData
 * @param {string[]} metaData.activeMeasures
 * @param {string} metaData.resModel
 * @param {string} metaData.title
 * @returns {Object}
 */
export function formatPivotForExport(table, metaData) {
    const { headers } = table;

    // Process column group header rows (all rows except the last, which is measures)
    let colGroupHeaderRows = headers.slice(0, -1);
    const measureRow = headers.at(-1).map(processHeader);

    // Remove the empty header on left side of first row
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
