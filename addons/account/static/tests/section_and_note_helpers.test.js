import {
    DISPLAY_TYPES,
    getPreviousSectionRecords,
    getRecordsUntilSection,
    getSectionRecords,
    hasNextSection,
    hasPreviousSection,
    isSectionOrNoteType,
    isSectionType,
    isSubSectionType,
    isTopSectionType,
} from "@account/components/section_and_note_fields_backend/section_and_note_helpers";
import { describe, expect, test } from "@odoo/hoot";

describe("section_and_note_helpers", () => {
    const rec = (id, displayType) => ({ id, data: { display_type: displayType } });
    const makeList = () => ({
        records: [
            rec("s1", DISPLAY_TYPES.SECTION),
            rec("l1", false),
            rec("ss1", DISPLAY_TYPES.SUBSECTION),
            rec("l2", false),
            rec("n1", DISPLAY_TYPES.NOTE),
            rec("s2", DISPLAY_TYPES.SECTION),
            rec("l3", false),
        ],
    });
    const ids = (records) => records.map((r) => r && r.id);

    test("type predicates", () => {
        expect(isSectionType(rec("x", DISPLAY_TYPES.SECTION))).toBe(true);
        expect(isSectionType(rec("x", DISPLAY_TYPES.SUBSECTION))).toBe(true);
        expect(isSectionType(rec("x", false))).toBe(false);
        expect(isSectionOrNoteType(rec("x", DISPLAY_TYPES.NOTE))).toBe(true);
        expect(isSectionOrNoteType(rec("x", false))).toBe(false);
        expect(isTopSectionType(rec("x", DISPLAY_TYPES.SECTION))).toBe(true);
        expect(isTopSectionType(rec("x", DISPLAY_TYPES.SUBSECTION))).toBe(false);
        expect(isSubSectionType(rec("x", DISPLAY_TYPES.SUBSECTION))).toBe(true);
    });

    test("getSectionRecords walks down to the next section (subsections included)", () => {
        const list = makeList();
        expect(ids(getSectionRecords(list, list.records[1]))).toEqual([
            "l1",
            "ss1",
            "l2",
            "n1",
        ]);
    });

    test("getSectionRecords stops at a subsection when subSection is true", () => {
        const list = makeList();
        expect(ids(getSectionRecords(list, list.records[1], true))).toEqual(["l1"]);
    });

    test("getPreviousSectionRecords returns the section above (delimiter included)", () => {
        const list = makeList();
        expect(ids(getPreviousSectionRecords(list, list.records[5]))).toEqual([
            "s1",
            "l1",
            "ss1",
            "l2",
            "n1",
        ]);
    });

    test("hasNextSection / hasPreviousSection", () => {
        const list = makeList();
        expect(hasNextSection(list, list.records[0])).toBe(true);
        expect(hasPreviousSection(list, list.records[0])).toBe(false);
        expect(hasNextSection(list, list.records[5])).toBe(false);
    });

    test("a record no longer in the list yields no records, index -1 and no next section", () => {
        // A section row added and then abandoned (leaveEditMode drops an untouched
        // new record) while the row menu still holds it: the helper must not walk
        // from findIndex()'s -1.
        const list = makeList();
        const abandoned = rec("s-new", DISPLAY_TYPES.SECTION);
        const { sectionRecords, sectionIndex } = getRecordsUntilSection(list, abandoned, true);
        expect(ids(sectionRecords)).toEqual([]);
        expect(sectionIndex).toBe(-1);
        expect(hasNextSection(list, abandoned)).toBe(false);
    });

    test("no section above yields an empty array and index -1 (no undefined entry)", () => {
        const list = makeList();
        expect(getPreviousSectionRecords(list, list.records[0])).toEqual([]);
        expect(getRecordsUntilSection(list, list.records[0], false).sectionIndex).toBe(
            -1,
        );
    });
});
