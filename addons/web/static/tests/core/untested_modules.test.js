// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { isX2Many, isX2ManyType } from "@web/core/field_types";
import {
    deserializeDate,
    deserializeDateTime,
    serializeDate,
    serializeDateTime,
} from "@web/core/l10n/date_serialization";
import { luxon } from "@web/core/l10n/luxon";
import { x2ManyCommands } from "@web/core/network/commands";
import { ASTType } from "@web/core/py_js/ast_type";
import { not } from "@web/core/tree/ast_utils";
import {
    COMPARATORS,
    TERM_OPERATORS_NEGATION,
    TERM_OPERATORS_NEGATION_EXTENDED,
} from "@web/core/tree/operators";
import { extractDigits } from "@web/core/utils/format/digits";
import { globalSingleton } from "@web/core/utils/global_singleton";

describe.current.tags("headless");

const { DateTime } = luxon;

describe("l10n/date_serialization", () => {
    test("an invalid DateTime serializes to false, not to 'Invalid DateTime'", () => {
        const invalid = DateTime.invalid("probe");
        expect(serializeDate(invalid)).toBe(false);
        expect(serializeDateTime(invalid)).toBe(false);
    });

    test("an unparseable string cannot round-trip into a plausible date", () => {
        const d = deserializeDate("not-a-date");
        expect(d.isValid).toBe(false);
        expect(serializeDate(d)).toBe(false);

        const dt = deserializeDateTime("not-a-datetime");
        expect(dt.isValid).toBe(false);
        expect(serializeDateTime(dt)).toBe(false);
    });

    test("absent values stay false", () => {
        for (const empty of [false, null, undefined, ""]) {
            expect(serializeDate(/** @type {any} */ (empty))).toBe(false);
            expect(serializeDateTime(/** @type {any} */ (empty))).toBe(false);
        }
    });

    test("a valid date round-trips through the server format", () => {
        expect(serializeDate(deserializeDate("2026-08-17"))).toBe("2026-08-17");
    });

    test("datetimes serialize in UTC whatever zone they carry", () => {
        const dt = deserializeDateTime("2026-08-17 12:00:00", { tz: "UTC" });
        expect(serializeDateTime(dt)).toBe("2026-08-17 12:00:00");
        expect(serializeDateTime(dt.setZone("America/New_York"))).toBe(
            "2026-08-17 12:00:00",
        );
    });
});

describe("utils/global_singleton", () => {
    test("a factory answering null is not re-run on every read", () => {
        let calls = 0;
        /** @type {() => any} */
        const factory = () => {
            calls++;
            return null;
        };
        globalSingleton("__test_null_singleton__", factory);
        globalSingleton("__test_null_singleton__", factory);
        globalSingleton("__test_null_singleton__", factory);
        expect(calls).toBe(1);
    });

    test("a falsy-but-present value is memoised", () => {
        let calls = 0;
        const factory = () => {
            calls++;
            return 0;
        };
        expect(globalSingleton("__test_zero_singleton__", factory)).toBe(0);
        expect(globalSingleton("__test_zero_singleton__", factory)).toBe(0);
        expect(calls).toBe(1);
    });

    test("distinct keys get distinct instances, one key one instance", () => {
        const a = globalSingleton("__test_key_a__", () => ({ tag: "a" }));
        const b = globalSingleton("__test_key_b__", () => ({ tag: "b" }));
        expect(a).not.toBe(b);
        expect(globalSingleton("__test_key_a__", () => ({ tag: "other" }))).toBe(a);
    });
});

describe("utils/format/digits", () => {
    test("JSON that parses but is not a digits pair is refused", () => {
        expect(extractDigits({ attrs: { digits: '"nonsense"' }, options: {} })).toBe(
            undefined,
        );
        expect(extractDigits({ attrs: { digits: "{}" }, options: {} })).toBe(undefined);
        expect(extractDigits({ attrs: { digits: "5" }, options: {} })).toBe(undefined);
        expect(extractDigits({ attrs: { digits: "[16]" }, options: {} })).toBe(
            undefined,
        );
        expect(extractDigits({ attrs: { digits: '[16, "2"]' }, options: {} })).toBe(
            undefined,
        );
    });

    test("unparseable JSON falls through to the options", () => {
        expect(extractDigits({ attrs: { digits: "(16, 2)" }, options: {} })).toBe(
            undefined,
        );
        expect(
            extractDigits({
                attrs: { digits: "(16, 2)" },
                options: { digits: [8, 3] },
            }),
        ).toEqual([8, 3]);
    });

    test("the attribute wins over the option", () => {
        expect(
            extractDigits({
                attrs: { digits: "[16, 2]" },
                options: { digits: [8, 3] },
            }),
        ).toEqual([16, 2]);
    });

    test("nothing declared is undefined", () => {
        expect(extractDigits({ attrs: {}, options: {} })).toBe(undefined);
    });
});

describe("network/commands", () => {
    test("every factory emits the three-slot shape the server expects", () => {
        expect(x2ManyCommands.create(false, { a: 1 })).toEqual([0, false, { a: 1 }]);
        expect(x2ManyCommands.update(7, { a: 1 })).toEqual([1, 7, { a: 1 }]);
        expect(x2ManyCommands.delete(7)).toEqual([2, 7, false]);
        expect(x2ManyCommands.unlink(7)).toEqual([3, 7, false]);
        expect(x2ManyCommands.link(7)).toEqual([4, 7, false]);
        expect(x2ManyCommands.clear()).toEqual([5, false, false]);
        expect(x2ManyCommands.set([1, 2])).toEqual([6, false, [1, 2]]);
    });

    test("`id` is stripped from the values, never sent alongside the slot", () => {
        expect(x2ManyCommands.create(false, { id: 9, a: 1 })).toEqual([
            0,
            false,
            { a: 1 },
        ]);
        expect(x2ManyCommands.update(7, { id: 9, a: 1 })).toEqual([1, 7, { a: 1 }]);
    });

    test("the caller's values object is not mutated", () => {
        const values = { id: 9, a: 1 };
        x2ManyCommands.create(false, values);
        x2ManyCommands.update(7, values);
        expect(values).toEqual({ id: 9, a: 1 });
    });

    test("a virtual id of 0 is not silently turned into false", () => {
        expect(x2ManyCommands.create(0, {})).toEqual([0, false, {}]);
    });
});

describe("tree/operators", () => {
    test("negating a domain operator twice returns the original", () => {
        for (const [op, negated] of Object.entries(TERM_OPERATORS_NEGATION)) {
            expect(TERM_OPERATORS_NEGATION[negated]).toBe(op, {
                message: `${op} -> ${negated} -> ${TERM_OPERATORS_NEGATION[negated]}`,
            });
        }
    });

    test("every COMPARATOR has an extended negation", () => {
        for (const op of COMPARATORS) {
            expect(typeof TERM_OPERATORS_NEGATION_EXTENDED[op]).toBe("string", {
                message: `COMPARATORS includes "${op}" with no extended negation`,
            });
        }
    });

    test("the python layer normalises = to == under double negation", () => {
        expect(
            TERM_OPERATORS_NEGATION_EXTENDED[TERM_OPERATORS_NEGATION_EXTENDED["="]],
        ).toBe("==");
        const notInvolutive = Object.keys(TERM_OPERATORS_NEGATION_EXTENDED).filter(
            (op) =>
                TERM_OPERATORS_NEGATION_EXTENDED[
                    TERM_OPERATORS_NEGATION_EXTENDED[op]
                ] !== op,
        );
        expect(notInvolutive).toEqual(["="]);
    });

    test("not() round-trips a comparison through the ast", () => {
        for (const op of COMPARATORS) {
            const ast = {
                type: ASTType.BinaryOperator,
                op,
                left: { type: ASTType.Name, value: "a" },
                right: { type: ASTType.Number, value: 1 },
            };
            const once = /** @type {any} */ (not(ast));
            expect(once.op).toBe(TERM_OPERATORS_NEGATION_EXTENDED[op]);
            expect(/** @type {any} */ (not(once)).op).toBe(
                TERM_OPERATORS_NEGATION_EXTENDED[TERM_OPERATORS_NEGATION_EXTENDED[op]],
            );
        }
    });
});

describe("field_types", () => {
    test("only one2many and many2many are x2many", () => {
        expect(isX2ManyType("one2many")).toBe(true);
        expect(isX2ManyType("many2many")).toBe(true);
        for (const type of ["many2one", "char", "integer", "reference", ""]) {
            expect(isX2ManyType(type)).toBe(false);
        }
    });

    test("isX2Many tolerates an absent field definition", () => {
        expect(isX2Many(null)).toBe(false);
        expect(isX2Many(undefined)).toBe(false);
        expect(isX2Many({})).toBe(false);
        expect(isX2Many({ type: "one2many" })).toBe(true);
    });
});
