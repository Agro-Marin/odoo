// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Domain } from "@web/core/domain";

describe.current.tags("headless");

/**
 * `Domain.contains` is the client's twin of the server's IN-MEMORY evaluator --
 * `Field._filter_like` / `_like_regex_parts` in `odoo/orm/fields/_field_sql.py`,
 * the one `filtered_domain` uses. It is NOT a twin of what PostgreSQL does for a
 * `search`, and the two server evaluators do not agree with each other.
 *
 * Both columns below are generated, neither is hand-written:
 *
 *  - `postgres` comes from a real PostgreSQL 18, asked the way the ORM asks it:
 *    the value bound as a parameter, wrapped `%value%` for the unanchored
 *    operators and verbatim for the anchored ones
 *    (`_field_sql.py::_condition_like_to_sql`);
 *  - `inMemory` comes from running the server's own `_like_regex_parts` over the
 *    same value.
 *
 * They agree on 25 of these 27 and differ on 2, both a value ending in a lone
 * backslash: PostgreSQL lets it escape the wrapper's closing `%`, so the pattern
 * ends in a literal percent, while `_like_regex_parts` sets its `escaped` flag
 * and falls out of the loop, dropping the backslash. The client follows the
 * in-memory reading, which is the right one for what `contains` is for --
 * recorded here so that if anyone ever reconciles the two on the server, this
 * file says which rows move and why.
 *
 * @type {[string, string, string, boolean, boolean][]}
 */
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
