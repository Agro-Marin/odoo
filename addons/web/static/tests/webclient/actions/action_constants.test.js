// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { parseActiveIds } from "@web/webclient/actions/action_constants";

describe.current.tags("desktop");

test("a well-formed list is parsed in order", () => {
    expect(parseActiveIds("1,2,3")).toEqual([1, 2, 3]);
    expect(parseActiveIds("5")).toEqual([5]);
    expect(parseActiveIds(5)).toEqual([5]);
});

test("nothing that is not a record id is ever emitted", () => {
    expect(parseActiveIds("1,x,3")).toEqual([]);
    expect(parseActiveIds("1,,3")).toEqual([]);
    expect(parseActiveIds("")).toEqual([]);
    expect(parseActiveIds("-1")).toEqual([]);
    expect(parseActiveIds("1.5")).toEqual([]);
    expect(parseActiveIds("0")).toEqual([]);
    expect(parseActiveIds("1,0")).toEqual([]);
});

test("exponent and whitespace forms are not ids either", () => {
    expect(parseActiveIds("1e3")).toEqual([]);
    expect(parseActiveIds(" 1")).toEqual([]);
    expect(parseActiveIds("0x10")).toEqual([]);
});

test("a corrupt list is rejected whole, not narrowed", () => {
    expect(parseActiveIds("11,22,oops")).toEqual([]);
});

test("anything that is not a string or a number yields no ids", () => {
    expect(parseActiveIds(/** @type {any} */ (undefined))).toEqual([]);
    expect(parseActiveIds(/** @type {any} */ (null))).toEqual([]);
    expect(parseActiveIds(/** @type {any} */ ([1, 2]))).toEqual([]);
    expect(parseActiveIds(/** @type {any} */ (1.5))).toEqual([]);
});
