/** @odoo-module native */

/**
 * Pure section-tree helpers for the section/note editable list.
 *
 * These functions operate only on a plain list-like object
 * (`{ records: [{ id, data: { display_type } }, ...] }`) and individual record
 * datapoints — no renderer/`this`, no DOM, no OWL. Keeping them here decouples
 * the section-tree math from SectionAndNoteListRenderer and makes it unit-testable
 * in isolation.
 */

export const DISPLAY_TYPES = {
    NOTE: "line_note",
    SECTION: "line_section",
    SUBSECTION: "line_subsection",
};

/** @returns {boolean} whether the record is a (top) section or a subsection. */
export function isSectionType(record) {
    return [DISPLAY_TYPES.SECTION, DISPLAY_TYPES.SUBSECTION].includes(
        record.data.display_type,
    );
}

/** @returns {boolean} whether the record is a section, subsection or note. */
export function isSectionOrNoteType(record) {
    return [
        DISPLAY_TYPES.SECTION,
        DISPLAY_TYPES.SUBSECTION,
        DISPLAY_TYPES.NOTE,
    ].includes(record.data.display_type);
}

/** @returns {boolean} whether the record is a top-level section. */
export function isTopSectionType(record) {
    return record.data.display_type === DISPLAY_TYPES.SECTION;
}

/** @returns {boolean} whether the record is a subsection. */
export function isSubSectionType(record) {
    return record.data.display_type === DISPLAY_TYPES.SUBSECTION;
}

/**
 * Walk the records above or below `record` up to the delimiting section.
 *
 * @param {{records: Array}} list
 * @param {Object} record the record to walk from
 * @param {boolean} asc walk downward (true) or upward (false)
 * @param {boolean} [subSection] stop at subsections too; defaults to whether
 *  `record` itself is a subsection
 * @returns {{sectionRecords: Array, sectionIndex: number}} the records in the
 *  section (delimiter included on the upward walk) and the delimiter index
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
        // Only prepend the delimiting section when one exists above; otherwise
        // index is -1 and list.records[-1] would push `undefined` into the array.
        if (index >= 0) {
            sectionRecords.unshift(list.records[index]);
        }
    }

    return {
        sectionRecords,
        sectionIndex: index,
    };
}

/** @returns {Array} the records of the section `record` belongs to, walking down. */
export function getSectionRecords(list, record, subSection) {
    const { sectionRecords } = getRecordsUntilSection(list, record, true, subSection);
    return sectionRecords;
}

/** @returns {Array} the records of the section immediately above `record`. */
export function getPreviousSectionRecords(list, record) {
    const { sectionRecords } = getRecordsUntilSection(list, record, false);
    return sectionRecords;
}

/** @returns {boolean} whether a same-type section follows `record`. */
export function hasNextSection(list, record) {
    const { sectionIndex } = getRecordsUntilSection(list, record, true);
    return (
        sectionIndex < list.records.length &&
        list.records[sectionIndex].data.display_type === record.data.display_type
    );
}

/** @returns {boolean} whether a same-type section precedes `record`. */
export function hasPreviousSection(list, record) {
    const { sectionIndex } = getRecordsUntilSection(list, record, false);
    return (
        sectionIndex >= 0 &&
        list.records[sectionIndex].data.display_type === record.data.display_type
    );
}
