import { insertAtSelection } from "@mail/utils/common/composer_insert";
import { expect, test } from "@odoo/hoot";

test("text mode: splices text at the cursor and moves the cursor after it", () => {
    const composer = { composerText: "Hello world", selection: { start: 5, end: 5 } };
    const positions = [];
    insertAtSelection(composer, " dear", {
        moveCursor: (position) => positions.push(position),
    });
    expect(composer.composerText).toBe("Hello dear world");
    expect(positions).toEqual([10]);
});

test("text mode: replaces the selected range", () => {
    const composer = { composerText: "Hello world", selection: { start: 6, end: 11 } };
    const positions = [];
    insertAtSelection(composer, "there", {
        moveCursor: (position) => positions.push(position),
    });
    expect(composer.composerText).toBe("Hello there");
    expect(positions).toEqual([11]);
});

test("HTML mode: inserts through the editor and records one history step", () => {
    const inserted = [];
    let steps = 0;
    const editor = {
        shared: {
            dom: { insert: (text) => inserted.push(text) },
            history: { addStep: () => steps++ },
        },
    };
    const composer = { composerText: "untouched", selection: { start: 0, end: 0 } };
    insertAtSelection(composer, "😊", {
        editor,
        moveCursor: () => expect.step("moveCursor"),
    });
    expect(inserted).toEqual(["😊"]);
    expect(steps).toBe(1);
    expect(composer.composerText).toBe("untouched");
    // the plain-text path (and its cursor move) must not run in HTML mode
    expect.verifySteps([]);
});
