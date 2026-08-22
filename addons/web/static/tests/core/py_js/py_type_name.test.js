// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { evaluateExpr } from "@web/core/py_js/py";
import { pyTypeName } from "@web/core/py_js/py_builtin";
import {
    PyDate,
    PyDateTime,
    PyRelativeDelta,
    PyTime,
    PyTimeDelta,
} from "@web/core/py_js/py_date";

describe.current.tags("headless");

describe("pyTypeName: temporal types", () => {
    test("each temporal class reports its Python type name", () => {
        expect(pyTypeName(PyDate.create(2024, 1, 1))).toBe("date");
        expect(pyTypeName(PyDateTime.create(2024, 1, 1, 0, 0, 0))).toBe("datetime");
        expect(pyTypeName(PyTime.create(1, 2, 3))).toBe("time");
        expect(pyTypeName(PyTimeDelta.create({ days: 1 }))).toBe("timedelta");
        expect(pyTypeName(PyRelativeDelta.create({ days: 1 }))).toBe("relativedelta");
    });

    test("the non-temporal branches still answer Python names", () => {
        expect(pyTypeName(null)).toBe("NoneType");
        expect(pyTypeName(undefined)).toBe("NoneType");
        expect(pyTypeName(true)).toBe("bool");
        expect(pyTypeName(1)).toBe("int");
        expect(pyTypeName(1.5)).toBe("float");
        expect(pyTypeName("x")).toBe("str");
        expect(pyTypeName([1])).toBe("list");
        expect(pyTypeName(new Set([1]))).toBe("set");
        expect(pyTypeName({ a: 1 })).toBe("dict");
    });

    test("the names reach the user through an operand-type error", () => {
        expect(() => evaluateExpr(`datetime.date(2024, 1, 1) + "x"`)).toThrow(
            /'date' and 'str'/,
        );
        expect(() =>
            evaluateExpr(`datetime.timedelta(days=1) * datetime.timedelta(days=1)`),
        ).toThrow(/'timedelta' and 'timedelta'/);
    });
});
