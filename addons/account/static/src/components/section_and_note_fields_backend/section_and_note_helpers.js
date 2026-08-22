/** @odoo-module native */

export const DISPLAY_TYPES = {
    NOTE: "line_note",
    SECTION: "line_section",
    SUBSECTION: "line_subsection",
};

/** @returns {boolean} */
export function isSectionType(record) {
    return [DISPLAY_TYPES.SECTION, DISPLAY_TYPES.SUBSECTION].includes(
        record.data.display_type,
    );
}

/** @returns {boolean} */
export function isSectionOrNoteType(record) {
    return [
        DISPLAY_TYPES.SECTION,
        DISPLAY_TYPES.SUBSECTION,
        DISPLAY_TYPES.NOTE,
    ].includes(record.data.display_type);
}

/** @returns {boolean} */
export function isTopSectionType(record) {
    return record.data.display_type === DISPLAY_TYPES.SECTION;
}

/** @returns {boolean} */
export function isSubSectionType(record) {
    return record.data.display_type === DISPLAY_TYPES.SUBSECTION;
}

/**
 * @param {{records: Array}} list
 * @param {Object} record
 * @param {boolean} asc
 * @param {boolean} [subSection]
 * @returns {{sectionRecords: Array, sectionIndex: number}}
 */
export function getRecordsUntilSection(list, record, asc, subSection) {
    const stopAtTypes = [DISPLAY_TYPES.SECTION];
    if (subSection ?? record.data.display_type === DISPLAY_TYPES.SUBSECTION) {
        stopAtTypes.push(DISPLAY_TYPES.SUBSECTION);
    }

    const sectionRecords = [];
    let index = list.records.findIndex((listRecord) => listRecord.id === record.id);
    if (asc) {
        sectionRecords.push(list.records[index]);
        index++;
        while (
            index < list.records.length &&
            !stopAtTypes.includes(list.records[index].data.display_type)
        ) {
            sectionRecords.push(list.records[index]);
            index++;
        }
    } else {
        index--;
        while (
            index >= 0 &&
            !stopAtTypes.includes(list.records[index].data.display_type)
        ) {
            sectionRecords.unshift(list.records[index]);
            index--;
        }
        if (index >= 0) {
            sectionRecords.unshift(list.records[index]);
        }
    }

    return {
        sectionRecords,
        sectionIndex: index,
    };
}

/** @returns {Array} */
export function getSectionRecords(list, record, subSection) {
    const { sectionRecords } = getRecordsUntilSection(list, record, true, subSection);
    return sectionRecords;
}

/** @returns {Array} */
export function getPreviousSectionRecords(list, record) {
    const { sectionRecords } = getRecordsUntilSection(list, record, false);
    return sectionRecords;
}

/** @returns {boolean} */
export function hasNextSection(list, record) {
    const { sectionIndex } = getRecordsUntilSection(list, record, true);
    return (
        sectionIndex < list.records.length &&
        list.records[sectionIndex].data.display_type === record.data.display_type
    );
}

/** @returns {boolean} */
export function hasPreviousSection(list, record) {
    const { sectionIndex } = getRecordsUntilSection(list, record, false);
    return (
        sectionIndex >= 0 &&
        list.records[sectionIndex].data.display_type === record.data.display_type
    );
}
