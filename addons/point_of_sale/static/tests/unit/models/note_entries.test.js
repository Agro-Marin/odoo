import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryAllTexts } from "@odoo/hoot-dom";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { parseNoteEntries } from "@point_of_sale/app/models/utils/note_entries";
import { getStrNotes } from "@point_of_sale/app/utils/order_change_receipts";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

describe("parseNoteEntries", () => {
    test("reads what the note editor writes", () => {
        expect(
            parseNoteEntries('[{"text":"no onions","colorIndex":3}]'),
        ).toEqual([{ text: "no onions", colorIndex: 3 }]);
    });

    test("an empty note is no entries, whichever way it is empty", () => {
        for (const empty of [undefined, false, "", "[]", []]) {
            expect(parseNoteEntries(empty)).toEqual([]);
        }
    });

    test("a note written as plain text is one entry, not a crash", () => {
        // pos.order.line.note is a Text column: an import, an integration or a
        // plain ORM write puts a sentence in it, and it used to reach an
        // unguarded JSON.parse inside a render.
        expect(parseNoteEntries("extra sauce")).toEqual([
            { text: "extra sauce", colorIndex: 0 },
        ]);
        expect(parseNoteEntries('{"text":"an object"}')).toEqual([
            { text: '{"text":"an object"}', colorIndex: 0 },
        ]);
    });

    test("a bare string inside the array is an entry too", () => {
        expect(parseNoteEntries(["a", { text: "b", colorIndex: 1 }])).toEqual([
            { text: "a", colorIndex: 0 },
            { text: "b", colorIndex: 1 },
        ]);
    });

    test("getStrNotes joins whatever the decoder found", () => {
        expect(getStrNotes('[{"text":"a"},{"text":"b"}]')).toBe("a, b");
        expect(getStrNotes("plain")).toBe("plain");
        expect(getStrNotes("")).toBe("");
        expect(getStrNotes(5)).toBe("");
    });
});

describe("an orderline renders every shape of note", () => {
    async function mountLine(note) {
        const store = await setupPosEnv();
        const order = await getFilledOrder(store);
        const line = order.lines[0];
        line.setNote(note);
        const component = await mountWithCleanup(Orderline, { props: { line } });
        return { line, component };
    }

    test("a JSON note renders as a tag", async () => {
        await mountLine('[{"text":"no onions","colorIndex":0}]');
        expect(queryAll(".internal-note-container")).toHaveLength(1);
        expect(queryAllTexts(".internal-note-container")).toEqual(["no onions"]);
    });

    test("a plain-text note renders instead of throwing", async () => {
        await mountLine("extra sauce");
        expect(queryAll(".internal-note-container")).toHaveLength(1);
        expect(queryAllTexts(".internal-note-container")).toEqual(["extra sauce"]);
    });

    test("clearing a note leaves no container and no note spacing", async () => {
        const { component } = await mountLine("");
        expect(queryAll(".internal-note-container")).toHaveLength(0);
        expect(component.infoListClasses).toBe("");
    });
});
