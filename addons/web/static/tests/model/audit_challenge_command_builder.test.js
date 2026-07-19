// @ts-check

/**
 * AUDIT CHALLENGE — `shouldEmitUnlink` contradicts its own contract.
 *
 * Its docstring states: "If the record was LINKed in this session, UNLINK
 * cancels the LINK (net effect: nothing happened)." But it splices out only the
 * LINK tuple, leaving any `[UPDATE, id]` behind — where the sibling
 * `shouldEmitDelete` does `ownCommands.splice(0)` and clears everything.
 *
 * The surviving UPDATE is not inert: `serializeCommands` keeps a command whose
 * record is still in `_cache`, and the UNLINK branch of the command engine
 * prunes `_unknownRecordCommands` and `_loadingStubIds` but NOT `_cache`. So the
 * save payload writes the user's edits into a record they just removed from the
 * relation and which was never linked to begin with.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    shouldEmitDelete,
    shouldEmitUnlink,
} from "@web/model/relational_model/command_builder";
import { x2ManyCommands } from "@web/model/relational_model/commands";

const { CREATE, UPDATE, LINK } = x2ManyCommands;

describe.current.tags("headless");

/** @param {any[][]} commands */
const own = (commands) => commands.map((command, index) => ({ command, index }));

describe("UNLINK cancelling a LINK leaves nothing behind", () => {
    test("DELETE clears every command for the id (reference behaviour)", () => {
        const ownCommands = own([
            [CREATE, "virtual_1", {}],
            [UPDATE, "virtual_1"],
        ]);
        expect(shouldEmitDelete(ownCommands)).toBe(false);
        expect(ownCommands.length).toBe(0);
    });

    test("UNLINK after LINK+UPDATE clears the UPDATE too", () => {
        const ownCommands = own([
            [LINK, 5, false],
            [UPDATE, 5],
        ]);
        expect(shouldEmitUnlink(ownCommands)).toBe(false);
        // Currently 1: the [UPDATE, 5] survives and still serializes, so saving
        // writes the edit into record 5 after the user removed that row.
        expect(ownCommands.length).toBe(0);
    });

    test("UNLINK without a LINK still emits and keeps the UPDATE (control)", () => {
        const ownCommands = own([[UPDATE, 3]]);
        expect(shouldEmitUnlink(ownCommands)).toBe(true);
        expect(ownCommands.length).toBe(1);
    });
});
