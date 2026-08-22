import { CTYPES } from "@html_editor/utils/content_types";
import { splitTextNode } from "@html_editor/utils/dom";
import {
    enforceWhitespace,
    getState,
    restoreState,
} from "@html_editor/utils/dom_state";
import { DIRECTIONS } from "@html_editor/utils/position";
import { describe, expect, test } from "@odoo/hoot";

import { setupEditor } from "../_helpers/editor.js";

describe("getState", () => {
    test("should recognize invisible space to the right", async () => {
        const { el } = await setupEditor("<p>a </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 1);
        expect(p.childNodes.length).toBe(2);
        const position = [p, 1];
        expect(getState(...position, DIRECTIONS.RIGHT)).toEqual({
            node: p.firstChild,
            direction: DIRECTIONS.RIGHT,
            cType: CTYPES.BLOCK_INSIDE,
        });
    });

    test("should recognize invisible space to the right (among consecutive space within content)", async () => {
        const { el } = await setupEditor("<p>a  b</p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 2);
        expect(p.childNodes.length).toBe(2);
        const position = [p, 1];
        expect(getState(...position, DIRECTIONS.RIGHT)).toEqual({
            node: p.firstChild,
            direction: DIRECTIONS.RIGHT,
            cType: CTYPES.CONTENT,
        });
    });

    test("should recognize visible space to the left (followed by consecutive space within content)", async () => {
        const { el } = await setupEditor("<p>a  b</p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 2);
        expect(p.childNodes.length).toBe(2);
        const position = [p, 1];
        expect(getState(...position, DIRECTIONS.LEFT)).toEqual({
            node: p.lastChild,
            direction: DIRECTIONS.LEFT,
            cType: CTYPES.SPACE,
        });
    });

    test("should recognize invisible space to the left (nothing after)", async () => {
        const { el } = await setupEditor("<p> </p>");
        const p = el.firstChild;
        p.append(document.createTextNode(""));
        expect(getState(p, 1, DIRECTIONS.LEFT)).toEqual({
            node: p.lastChild,
            direction: DIRECTIONS.LEFT,
            cType: CTYPES.BLOCK_INSIDE,
        });
    });

    test("should recognize invisible space to the left (more space after)", async () => {
        const { el } = await setupEditor("<p>    </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 1);
        expect(getState(p, 1, DIRECTIONS.LEFT)).toEqual({
            node: p.lastChild,
            direction: DIRECTIONS.LEFT,
            cType: CTYPES.BLOCK_INSIDE,
        });
    });

    test("should recognize invisible space to the left (br after)", async () => {
        const { el } = await setupEditor("<p> <br></p>");
        const p = el.firstChild;
        expect(getState(p, 1, DIRECTIONS.LEFT)).toEqual({
            node: p.lastChild,
            direction: DIRECTIONS.LEFT,
            cType: CTYPES.BLOCK_INSIDE,
        });
    });
});

describe("restoreState", () => {
    test("should restore invisible space to the left (looking right)", async () => {
        const { el } = await setupEditor("<p>a b</p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 2);
        const rule = restoreState({
            node: p.firstChild,
            direction: DIRECTIONS.RIGHT,
            cType: CTYPES.BLOCK_INSIDE,
        });
        expect(rule.spaceVisibility).not.toBe(true);
    });

    test("should restore visible space to the left (looking right) (among consecutive space within content)", async () => {
        const { el } = await setupEditor("<p>a  </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 2);
        const rule = restoreState({
            node: p.firstChild,
            direction: DIRECTIONS.RIGHT,
            cType: CTYPES.CONTENT,
        });
        expect(rule.spaceVisibility).toBe(true);
    });

    test("should restore visible space to the right (looking left) (followed by consecutive space within content)", async () => {
        const { el } = await setupEditor("<p>a  </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 2);
        const rule = restoreState({
            node: p.lastChild,
            direction: DIRECTIONS.LEFT,
            cType: CTYPES.SPACE,
        });
        expect(rule.spaceVisibility).not.toBe(true);
    });

    test("should restore invisible space to the right (looking left) (nothing after)", async () => {
        const { el } = await setupEditor("<p>a </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 1);
        const rule = restoreState({
            node: p.lastChild,
            direction: DIRECTIONS.LEFT,
            cType: CTYPES.BLOCK_INSIDE,
        });
        expect(rule.spaceVisibility).not.toBe(true);
    });

    test("should restore invisible space to the right (looking left) (more space after)", async () => {
        const { el } = await setupEditor("<p>a    </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 2);
        const rule = restoreState({
            node: p.lastChild,
            direction: DIRECTIONS.LEFT,
            cType: CTYPES.BLOCK_INSIDE,
        });
        expect(rule.spaceVisibility).not.toBe(true);
    });

    test("should restore invisible space to the right (looking left) (br after)", async () => {
        const { el } = await setupEditor("<p>a <br></p>");
        const p = el.firstChild;
        const rule = restoreState({
            node: p.lastChild,
            direction: DIRECTIONS.LEFT,
            cType: CTYPES.BLOCK_INSIDE,
        });
        expect(rule.spaceVisibility).not.toBe(true);
    });
});

describe("enforceWhitespace", () => {
    test("should enforce invisible space to the left", async () => {
        const { el } = await setupEditor("<p>a b</p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 2);
        enforceWhitespace(p, 1, DIRECTIONS.LEFT, { spaceVisibility: false });
        expect(p.innerHTML).toBe("ab");
    });

    test("should restore visible space to the left (among consecutive space within content)", async () => {
        const { el } = await setupEditor("<p>a  </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 2);
        enforceWhitespace(p, 1, DIRECTIONS.LEFT, { spaceVisibility: true });
        expect(p.innerHTML).toBe("a&nbsp; ");
    });

    test("should not enforce already invisible space to the right (followed by consecutive space within content)", async () => {
        const { el } = await setupEditor("<p>a  </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 2);
        enforceWhitespace(p, 0, DIRECTIONS.RIGHT, { spaceVisibility: false });
        expect(p.innerHTML).toBe("a  ");
    });

    test("should not enforce already invisible space to the right (nothing after)", async () => {
        const { el } = await setupEditor("<p>a </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 1);
        enforceWhitespace(p, 0, DIRECTIONS.RIGHT, { spaceVisibility: false });
        expect(p.innerHTML).toBe("a ");
    });

    test("should not enforce already invisible space to the left (more space after)", async () => {
        const { el } = await setupEditor("<p>a    </p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 1);
        enforceWhitespace(p, 0, DIRECTIONS.RIGHT, { spaceVisibility: false });
        expect(p.innerHTML).toBe("a    ");
    });

    test("should not enforce already invisible space to the left (br after)", async () => {
        const { el } = await setupEditor("<p>a <br></p>");
        const p = el.firstChild;
        splitTextNode(p.firstChild, 1);
        enforceWhitespace(p, 0, DIRECTIONS.RIGHT, { spaceVisibility: false });
        expect(p.innerHTML).toBe("a <br>");
    });
});
