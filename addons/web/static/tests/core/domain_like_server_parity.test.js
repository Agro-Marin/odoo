// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Domain } from "@web/core/domain";

describe.current.tags("headless");

/** @type {[string, string, string, boolean, boolean][]} */
const SERVER = [
    ["abc", "abc", "like", true, true],
    ["abc", "b", "like", true, true],
    ["abc", "", "like", true, true],
    ["abc", "a_c", "like", true, true],
    ["abc", "a%c", "like", true, true],
    ["ac", "a%c", "like", true, true],
    ["a%c", "a\\%c", "like", true, true],
    ["abc", "a\\%c", "like", false, false],
    ["abc", "ab\\", "like", false, true],
    ["ab%", "ab\\", "like", true, true],
    ["ab\\", "ab\\", "like", false, true],
    ["a\\c", "a\\\\c", "like", true, true],
    ["ABC", "abc", "ilike", true, true],
    ["abc", "ABC", "ilike", true, true],
    ["abc", "abc", "=like", true, true],
    ["abc", "a_c", "=like", true, true],
    ["abc", "a%", "=like", true, true],
    ["abc", "b", "=like", false, false],
    ["abc", "%b%", "=like", true, true],
    ["ABC", "a%", "=ilike", true, true],
    ["abc", "", "=like", false, false],
    ["aXc", "a_c", "like", true, true],
    ["abc", "%", "like", true, true],
    ["", "", "like", true, true],
    ["100%", "100\\%", "like", true, true],
    ["a_b", "a\\_b", "like", true, true],
    ["axb", "a\\_b", "like", false, false],
];

describe("Domain.contains follows the server's in-memory LIKE evaluator", () => {
    test("every pattern, against the evaluator it mirrors", () => {
        /** @type {string[]} */
        const diffs = [];
        for (const [subject, value, operator, , inMemory] of SERVER) {
            let got;
            try {
                got = new Domain([["f", operator, value]]).contains({ f: subject });
            } catch (error) {
                got = `THREW:${error.constructor.name}`;
            }
            if (got !== inMemory) {
                diffs.push(
                    `${JSON.stringify(subject)} ${operator} ${JSON.stringify(value)}` +
                        `  in-memory=${inMemory}  client=${got}`,
                );
            }
        }
        expect(diffs).toEqual([]);
    });

    test("and the two server evaluators disagree on exactly these", () => {
        const split = SERVER.filter(([, , , pg, mem]) => pg !== mem).map(
            ([subject, value, operator]) =>
                `${JSON.stringify(subject)} ${operator} ${JSON.stringify(value)}`,
        );
        expect(split).toEqual([
            String.raw`"abc" like "ab\\"`,
            String.raw`"ab\\" like "ab\\"`,
        ]);
    });
});
