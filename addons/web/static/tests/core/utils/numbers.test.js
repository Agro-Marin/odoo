// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { allowTranslations, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { formatFieldFloat as formatterFloat } from "@web/core/formatters";
import { localization } from "@web/core/l10n/localization";
import {
    clamp,
    floatIsZero,
    formatFloat,
    humanNumber,
    range,
    roundDecimals,
    roundPrecision,
} from "@web/core/utils/format/numbers";

describe.current.tags("headless");

test("clamp", () => {
    expect(clamp(-5, 0, 10)).toBe(0);
    expect(clamp(0, 0, 10)).toBe(0);
    expect(clamp(2, 0, 10)).toBe(2);
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(7, 0, 10)).toBe(7);
    expect(clamp(10, 0, 10)).toBe(10);
    expect(clamp(15, 0, 10)).toBe(10);
});

test("range", () => {
    expect(range(0, 10)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    expect(range(0, 35, 5)).toEqual([0, 5, 10, 15, 20, 25, 30]);
    expect(range(-10, 6, 2)).toEqual([-10, -8, -6, -4, -2, 0, 2, 4]);
    expect(range(0, -10, -1)).toEqual([0, -1, -2, -3, -4, -5, -6, -7, -8, -9]);
    expect(range(4, -4, -1)).toEqual([4, 3, 2, 1, 0, -1, -2, -3]);
    expect(range(1, 4, -1)).toEqual([]);
    expect(range(1, -4, 1)).toEqual([]);
    expect(range(0, 5, 2)).toEqual([0, 2, 4]);
    expect(range(0, 10, 3)).toEqual([0, 3, 6, 9]);
    expect(range(0, -5, -2)).toEqual([0, -2, -4]);
});

describe("roundPrecision", () => {
    test("default method (HALF-UP)", () => {
        expect(roundPrecision(1.0, 1)).toBe(1);
        expect(roundPrecision(1.0, 0.1)).toBe(1);
        expect(roundPrecision(1.0, 0.01)).toBe(1);
        expect(roundPrecision(1.0, 0.001)).toBe(1);
        expect(roundPrecision(1.0, 0.0001)).toBe(1);
        expect(roundPrecision(1.0, 0.00001)).toBe(1);
        expect(roundPrecision(1.0, 0.000001)).toBe(1);
        expect(roundPrecision(1.0, 0.0000001)).toBe(1);
        expect(roundPrecision(1.0, 0.00000001)).toBe(1);
        expect(roundPrecision(0.5, 1)).toBe(1);
        expect(roundPrecision(-0.5, 1)).toBe(-1);
        expect(roundPrecision(2.6745, 0.001)).toBe(2.675);
        expect(roundPrecision(-2.6745, 0.001)).toBe(-2.675);
        expect(roundPrecision(2.6744, 0.001)).toBe(2.674);
        expect(roundPrecision(-2.6744, 0.001)).toBe(-2.674);
        expect(roundPrecision(0.0004, 0.001)).toBe(0);
        expect(roundPrecision(-0.0004, 0.001)).toBe(0);
        expect(roundPrecision(357.4555, 0.001)).toBe(357.456);
        expect(roundPrecision(-357.4555, 0.001)).toBe(-357.456);
        expect(roundPrecision(457.4554, 0.001)).toBe(457.455);
        expect(roundPrecision(-457.4554, 0.001)).toBe(-457.455);
        expect(roundPrecision(-457.4554, 0.05)).toBe(-457.45);
        expect(roundPrecision(457.444, 0.5)).toBe(457.5);
        expect(roundPrecision(457.3, 5)).toBe(455);
        expect(roundPrecision(457.5, 5)).toBe(460);
        expect(roundPrecision(457.1, 3)).toBe(456);

        expect(roundPrecision(2.6735, 0.001)).toBe(2.674);
        expect(roundPrecision(-2.6735, 0.001)).toBe(-2.674);
        expect(roundPrecision(2.6745, 0.001)).toBe(2.675);
        expect(roundPrecision(-2.6745, 0.001)).toBe(-2.675);
        expect(roundPrecision(2.6744, 0.001)).toBe(2.674);
        expect(roundPrecision(-2.6744, 0.001)).toBe(-2.674);
        expect(roundPrecision(0.0004, 0.001)).toBe(0);
        expect(roundPrecision(-0.0004, 0.001)).toBe(-0);
        expect(roundPrecision(357.4555, 0.001)).toBe(357.456);
        expect(roundPrecision(-357.4555, 0.001)).toBe(-357.456);
        expect(roundPrecision(457.4554, 0.001)).toBe(457.455);
        expect(roundPrecision(-457.4554, 0.001)).toBe(-457.455);
    });

    test("DOWN", () => {
        expect(roundPrecision(2.425, 0.001, "DOWN")).toBe(2.425);
        expect(roundPrecision(2.4249, 0.001, "DOWN")).toBe(2.424);
        expect(roundPrecision(-2.425, 0.001, "DOWN")).toBe(-2.425);
        expect(roundPrecision(-2.4249, 0.001, "DOWN")).toBe(-2.424);
        expect(roundPrecision(-2.5, 0.001, "DOWN")).toBe(-2.5);
        expect(roundPrecision(1.8, 1, "DOWN")).toBe(1);
        expect(roundPrecision(-1.8, 1, "DOWN")).toBe(-1);
    });

    test("HALF-DOWN", () => {
        expect(roundPrecision(2.6735, 0.001, "HALF-DOWN")).toBe(2.673);
        expect(roundPrecision(-2.6735, 0.001, "HALF-DOWN")).toBe(-2.673);
        expect(roundPrecision(2.6745, 0.001, "HALF-DOWN")).toBe(2.674);
        expect(roundPrecision(-2.6745, 0.001, "HALF-DOWN")).toBe(-2.674);
        expect(roundPrecision(2.6744, 0.001, "HALF-DOWN")).toBe(2.674);
        expect(roundPrecision(-2.6744, 0.001, "HALF-DOWN")).toBe(-2.674);
        expect(roundPrecision(0.0004, 0.001, "HALF-DOWN")).toBe(0);
        expect(roundPrecision(-0.0004, 0.001, "HALF-DOWN")).toBe(-0);
        expect(roundPrecision(357.4555, 0.001, "HALF-DOWN")).toBe(357.455);
        expect(roundPrecision(-357.4555, 0.001, "HALF-DOWN")).toBe(-357.455);
        expect(roundPrecision(457.4554, 0.001, "HALF-DOWN")).toBe(457.455);
        expect(roundPrecision(-457.4554, 0.001, "HALF-DOWN")).toBe(-457.455);
    });

    test("HALF-UP", () => {
        expect(roundPrecision(2.6735, 0.001, "HALF-UP")).toBe(2.674);
        expect(roundPrecision(-2.6735, 0.001, "HALF-UP")).toBe(-2.674);
        expect(roundPrecision(2.6745, 0.001, "HALF-UP")).toBe(2.675);
        expect(roundPrecision(-2.6745, 0.001, "HALF-UP")).toBe(-2.675);
        expect(roundPrecision(2.6744, 0.001, "HALF-UP")).toBe(2.674);
        expect(roundPrecision(-2.6744, 0.001, "HALF-UP")).toBe(-2.674);
        expect(roundPrecision(0.0004, 0.001, "HALF-UP")).toBe(0);
        expect(roundPrecision(-0.0004, 0.001, "HALF-UP")).toBe(-0);
        expect(roundPrecision(357.4555, 0.001, "HALF-UP")).toBe(357.456);
        expect(roundPrecision(-357.4555, 0.001, "HALF-UP")).toBe(-357.456);
        expect(roundPrecision(457.4554, 0.001, "HALF-UP")).toBe(457.455);
        expect(roundPrecision(-457.4554, 0.001, "HALF-UP")).toBe(-457.455);
    });

    test("HALF-EVEN", () => {
        expect(roundPrecision(5.015, 0.01, "HALF-EVEN")).toBe(5.02);
        expect(roundPrecision(-5.015, 0.01, "HALF-EVEN")).toBe(-5.02);
        expect(roundPrecision(5.025, 0.01, "HALF-EVEN")).toBe(5.02);
        expect(roundPrecision(-5.025, 0.01, "HALF-EVEN")).toBe(-5.02);
        expect(roundPrecision(2.6735, 0.001, "HALF-EVEN")).toBe(2.674);
        expect(roundPrecision(-2.6735, 0.001, "HALF-EVEN")).toBe(-2.674);
        expect(roundPrecision(2.6745, 0.001, "HALF-EVEN")).toBe(2.674);
        expect(roundPrecision(-2.6745, 0.001, "HALF-EVEN")).toBe(-2.674);
        expect(roundPrecision(2.6744, 0.001, "HALF-EVEN")).toBe(2.674);
        expect(roundPrecision(-2.6744, 0.001, "HALF-EVEN")).toBe(-2.674);
        expect(roundPrecision(0.0004, 0.001, "HALF-EVEN")).toBe(0);
        expect(roundPrecision(-0.0004, 0.001, "HALF-EVEN")).toBe(-0);
        expect(roundPrecision(357.4555, 0.001, "HALF-EVEN")).toBe(357.456);
        expect(roundPrecision(-357.4555, 0.001, "HALF-EVEN")).toBe(-357.456);
        expect(roundPrecision(457.4554, 0.001, "HALF-EVEN")).toBe(457.455);
        expect(roundPrecision(-457.4554, 0.001, "HALF-EVEN")).toBe(-457.455);
    });

    test("parity with the server's float_round", () => {
        expect(roundPrecision(-2.5, 1, "HALF-UP")).toBe(-3);
        expect(roundPrecision(-2.5, 1, "HALF-DOWN")).toBe(-2);
        expect(roundPrecision(-2.5, 1, "HALF-EVEN")).toBe(-2);
        expect(roundPrecision(-3.5, 1, "HALF-EVEN")).toBe(-4);
        expect(roundPrecision(-504607249.8149996, 0.01, "HALF-UP")).toBe(-504607249.82);
        expect(roundPrecision(-259351980657.49976, 1, "HALF-UP")).toBe(-259351980658);

        expect(roundPrecision(6396313.599999995, 1e-8, "UP")).toBe(6396313.6);
        expect(roundPrecision(-6396313.599999995, 1e-8, "UP")).toBe(-6396313.6);
        expect(roundPrecision(6396313.600000004, 1e-8, "DOWN")).toBe(6396313.6);
        expect(roundPrecision(-6396313.600000004, 1e-8, "DOWN")).toBe(-6396313.6);
        expect(roundPrecision(644245094.4000005, 1e-6, "UP")).toBe(644245094.400001);
        expect(roundPrecision(644245094.4000003, 1e-6, "DOWN")).toBe(644245094.4);
        expect(roundPrecision(63565515980.79995, 1e-4, "UP")).toBe(63565515980.8);
        expect(roundPrecision(63565515980.80003, 1e-4, "DOWN")).toBe(63565515980.8);
        expect(roundPrecision(6377167441100.805, 0.01, "UP")).toBe(6377167441100.81);
        expect(roundPrecision(6487118603878.403, 0.01, "DOWN")).toBe(6487118603878.4);

        expect(roundPrecision(11324620.800000004, 1e-8, "HALF-EVEN")).toBe(11324620.8);
        expect(roundPrecision(1127428915.2000005, 1e-6, "HALF-EVEN")).toBe(
            1127428915.2,
        );
        expect(roundPrecision(11434920928870.406, 0.01, "HALF-EVEN")).toBe(
            11434920928870.4,
        );
    });

    test("UP", () => {
        expect(roundPrecision(8.175, 0.001, "UP")).toBe(8.175);
        expect(roundPrecision(8.1751, 0.001, "UP")).toBe(8.176);
        expect(roundPrecision(-8.175, 0.001, "UP")).toBe(-8.175);
        expect(roundPrecision(-8.1751, 0.001, "UP")).toBe(-8.176);
        expect(roundPrecision(-6.0, 0.001, "UP")).toBe(-6);
        expect(roundPrecision(1.8, 1, "UP")).toBe(2);
        expect(roundPrecision(-1.8, 1, "UP")).toBe(-2);
    });

    test("large magnitudes (no spurious digits)", () => {
        for (const value of [
            5.6e12, 1e13, 1.23456789e14, 1e15, -1e13, -1.23456789e14,
        ]) {
            for (const method of ["HALF-UP", "HALF-DOWN", "HALF-EVEN"]) {
                expect(roundPrecision(value, 0.01, method)).toBe(value);
                expect(roundPrecision(value, 1, method)).toBe(value);
            }
        }
        expect(roundPrecision(1e13, 0.01)).toBe(1e13);
        expect(roundDecimals(1e13, 2)).toBe(1e13);
        expect(roundDecimals(-1.23456789e14, 2)).toBe(-1.23456789e14);
        for (const method of ["UP", "DOWN"]) {
            expect(roundPrecision(1e13, 0.01, method)).toBe(1e13);
            expect(roundPrecision(5.6e12, 0.01, method)).toBe(5.6e12);
            expect(roundPrecision(1e13, 1, method)).toBe(1e13);
            expect(roundPrecision(-1e13, 0.01, method)).toBe(-1e13);
        }
        expect(roundPrecision(1e13 + 0.5, 1, "HALF-UP")).toBe(1e13 + 1);
        expect(roundPrecision(1e13 + 0.5, 1, "HALF-DOWN")).toBe(1e13);
        expect(roundPrecision(-(1e13 + 0.5), 1, "HALF-UP")).toBe(-(1e13 + 1));
    });

    test("representation-error rescue is preserved", () => {
        expect(roundPrecision(0.145, 0.01)).toBe(0.15);
        expect(roundPrecision(1.005, 0.01)).toBe(1.01);
        expect(roundPrecision(2.675, 0.01)).toBe(2.68);
        expect(roundPrecision(2.665, 0.01)).toBe(2.67);
        expect(roundPrecision(0.045, 0.01)).toBe(0.05);
        expect(roundPrecision(-0.145, 0.01)).toBe(-0.15);
        expect(roundPrecision(-2.675, 0.01)).toBe(-2.68);
        expect(roundPrecision(1.2345675, 1e-6)).toBe(1.234568);
        expect(roundPrecision(1.234567891234, 1e-12)).toBe(1.234567891234);
    });
});

test("roundDecimals: the precision table is identical to the string build", () => {
    for (let d = -3; d <= 20; d++) {
        const fromString = parseFloat("1e" + -d);
        for (const v of [
            0, 0.5, -0.5, 1.005, -2.675, 2.6745, 1234567.891, 1e-7, -0.0001, 1e13,
        ]) {
            expect(roundDecimals(v, d)).toBe(roundPrecision(v, fromString), {
                message: `roundDecimals(${v}, ${d})`,
            });
        }
    }
});

test("roundDecimals", () => {
    expect(roundDecimals(1.0, 0)).toBe(1);
    expect(roundDecimals(1.0, 1)).toBe(1);
    expect(roundDecimals(1.0, 2)).toBe(1);
    expect(roundDecimals(1.0, 3)).toBe(1);
    expect(roundDecimals(1.0, 4)).toBe(1);
    expect(roundDecimals(1.0, 5)).toBe(1);
    expect(roundDecimals(1.0, 6)).toBe(1);
    expect(roundDecimals(1.0, 7)).toBe(1);
    expect(roundDecimals(1.0, 8)).toBe(1);
    expect(roundDecimals(0.5, 0)).toBe(1);
    expect(roundDecimals(-0.5, 0)).toBe(-1);
    expect(roundDecimals(2.6745, 3)).toBe(2.675);
    expect(roundDecimals(-2.6745, 3)).toBe(-2.675);
    expect(roundDecimals(2.6744, 3)).toBe(2.674);
    expect(roundDecimals(-2.6744, 3)).toBe(-2.674);
    expect(roundDecimals(0.0004, 3)).toBe(0);
    expect(roundDecimals(-0.0004, 3)).toBe(0);
    expect(roundDecimals(357.4555, 3)).toBe(357.456);
    expect(roundDecimals(-357.4555, 3)).toBe(-357.456);
    expect(roundDecimals(457.4554, 3)).toBe(457.455);
    expect(roundDecimals(-457.4554, 3)).toBe(-457.455);
});

test("humanNumber rounds negatives away from zero (symmetric with positives)", () => {
    allowTranslations();
    patchWithCleanup(localization, {
        decimalPoint: ".",
        grouping: [3, 0],
        thousandsSep: ",",
    });
    expect(humanNumber(1.5, { decimals: 0 })).toBe("2");
    expect(humanNumber(-1.5, { decimals: 0 })).toBe("-2");
    expect(humanNumber(0.5, { decimals: 0 })).toBe("1");
    expect(humanNumber(-0.5, { decimals: 0 })).toBe("-1");
    expect(humanNumber(2.5, { decimals: 0 })).toBe("3");
    expect(humanNumber(-2.5, { decimals: 0 })).toBe("-3");
});

test("floatIsZero", () => {
    expect(floatIsZero(1, 0)).toBe(false);
    expect(floatIsZero(0.9999, 0)).toBe(false);
    expect(floatIsZero(0.50001, 0)).toBe(false);
    expect(floatIsZero(0.5, 0)).toBe(false);
    expect(floatIsZero(0.49999, 0)).toBe(true);
    expect(floatIsZero(0, 0)).toBe(true);
    expect(floatIsZero(-0.49999, 0)).toBe(true);
    expect(floatIsZero(-0.50001, 0)).toBe(false);
    expect(floatIsZero(-0.5, 0)).toBe(false);
    expect(floatIsZero(-0.9999, 0)).toBe(false);
    expect(floatIsZero(-1, 0)).toBe(false);

    expect(floatIsZero(0.1, 1)).toBe(false);
    expect(floatIsZero(0.099999, 1)).toBe(false);
    expect(floatIsZero(0.050001, 1)).toBe(false);
    expect(floatIsZero(0.05, 1)).toBe(false);
    expect(floatIsZero(0.049999, 1)).toBe(true);
    expect(floatIsZero(0, 1)).toBe(true);
    expect(floatIsZero(-0.049999, 1)).toBe(true);
    expect(floatIsZero(-0.05, 1)).toBe(false);
    expect(floatIsZero(-0.050001, 1)).toBe(false);
    expect(floatIsZero(-0.099999, 1)).toBe(false);
    expect(floatIsZero(-0.1, 1)).toBe(false);

    expect(floatIsZero(0.01, 2)).toBe(false);
    expect(floatIsZero(0.0099999, 2)).toBe(false);
    expect(floatIsZero(0.005, 2)).toBe(false);
    expect(floatIsZero(0.0050001, 2)).toBe(false);
    expect(floatIsZero(0.0049999, 2)).toBe(true);
    expect(floatIsZero(0, 2)).toBe(true);
    expect(floatIsZero(-0.0049999, 2)).toBe(true);
    expect(floatIsZero(-0.0050001, 2)).toBe(false);
    expect(floatIsZero(-0.005, 2)).toBe(false);
    expect(floatIsZero(-0.0099999, 2)).toBe(false);
    expect(floatIsZero(-0.01, 2)).toBe(false);

    expect(floatIsZero(0.0001, 4)).toBe(false);
    expect(floatIsZero(0.000099999, 4)).toBe(false);
    expect(floatIsZero(0.00005, 4)).toBe(false);
    expect(floatIsZero(0.000050001, 4)).toBe(false);
    expect(floatIsZero(0.000049999, 4)).toBe(true);
    expect(floatIsZero(0, 4)).toBe(true);
    expect(floatIsZero(-0.000049999, 4)).toBe(true);
    expect(floatIsZero(-0.000050001, 4)).toBe(false);
    expect(floatIsZero(-0.00005, 4)).toBe(false);
    expect(floatIsZero(-0.000099999, 4)).toBe(false);
    expect(floatIsZero(-0.0001, 4)).toBe(false);

    expect(floatIsZero(0.00001, 5)).toBe(false);
    expect(floatIsZero(0.0000099999, 5)).toBe(false);
    expect(floatIsZero(0.000005, 5)).toBe(false);
    expect(floatIsZero(0.0000050001, 5)).toBe(false);
    expect(floatIsZero(0.0000049999, 5)).toBe(true);
    expect(floatIsZero(0, 5)).toBe(true);
    expect(floatIsZero(-0.0000049999, 5)).toBe(true);
    expect(floatIsZero(-0.0000050001, 5)).toBe(false);
    expect(floatIsZero(-0.000005, 5)).toBe(false);
    expect(floatIsZero(-0.0000099999, 5)).toBe(false);
    expect(floatIsZero(-0.00001, 5)).toBe(false);

    expect(floatIsZero(0.0000001, 7)).toBe(false);
    expect(floatIsZero(0.000000099999, 7)).toBe(false);
    expect(floatIsZero(0.00000005, 7)).toBe(false);
    expect(floatIsZero(0.000000050001, 7)).toBe(false);
    expect(floatIsZero(0.000000049999, 7)).toBe(true);
    expect(floatIsZero(0, 7)).toBe(true);
    expect(floatIsZero(-0.000000049999, 7)).toBe(true);
    expect(floatIsZero(-0.000000050001, 7)).toBe(false);
    expect(floatIsZero(-0.00000005, 7)).toBe(false);
    expect(floatIsZero(-0.000000099999, 7)).toBe(false);
    expect(floatIsZero(-0.0000001, 7)).toBe(false);
});

describe("formatFloat", () => {
    test("precision", () => {
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });

        let options = {};
        expect(formatFloat(3, options)).toBe("3.00");
        expect(formatFloat(3.1, options)).toBe("3.10");
        expect(formatFloat(3.12, options)).toBe("3.12");
        expect(formatFloat(3.129, options)).toBe("3.13");

        options = { digits: [15, 3] };
        expect(formatFloat(3, options)).toBe("3.000");
        expect(formatFloat(3.1, options)).toBe("3.100");
        expect(formatFloat(3.123, options)).toBe("3.123");
        expect(formatFloat(3.1239, options)).toBe("3.124");

        options = { minDigits: 3 };
        expect(formatFloat(0, options)).toBe("0.000");
        expect(formatFloat(3, options)).toBe("3.000");
        expect(formatFloat(3.1, options)).toBe("3.100");
        expect(formatFloat(3.123, options)).toBe("3.123");
        expect(formatFloat(3.1239, options)).toBe("3.1239");
        expect(formatFloat(3.1231239, options)).toBe("3.123124");
        // eslint-disable-next-line no-loss-of-precision -- high-precision literal is deliberate test input
        expect(formatFloat(1234567890.123456789, options)).toBe("1,234,567,890.12346");

        options = { minDigits: 3, digits: [15, 4] };
        expect(formatFloat(3, options)).toBe("3.000");
        expect(formatFloat(3.1, options)).toBe("3.100");
        expect(formatFloat(3.123, options)).toBe("3.123");
        expect(formatFloat(3.1239, options)).toBe("3.1239");
        expect(formatFloat(3.1234567, options)).toBe("3.1235");
    });

    test("localized", () => {
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });
        expect(formatFloat(1000000)).toBe("1,000,000.00");

        const options = { grouping: [3, 2, -1], decimalPoint: "?", thousandsSep: "€" };
        expect(formatFloat(106500, options)).toBe("1€06€500?00");

        expect(formatFloat(1500, { thousandsSep: "" })).toBe("1500.00");
        expect(formatFloat(-1.01)).toBe("-1.01");
        expect(formatFloat(-0.01)).toBe("-0.01");

        expect(formatFloat(38.0001, { trailingZeros: false })).toBe("38");
        expect(formatFloat(38.1, { trailingZeros: false })).toBe("38.1");
        expect(formatFloat(38.0001, { digits: [16, 0], trailingZeros: false })).toBe(
            "38",
        );

        patchWithCleanup(localization, { grouping: [3, 3, 3, 3] });
        expect(formatFloat(1000000)).toBe("1,000,000.00");

        patchWithCleanup(localization, { grouping: [3, 2, -1] });
        expect(formatFloat(106500)).toBe("1,06,500.00");

        patchWithCleanup(localization, { grouping: [1, 2, -1] });
        expect(formatFloat(106500)).toBe("106,50,0.00");

        patchWithCleanup(localization, {
            decimalPoint: "!",
            grouping: [2, 0],
            thousandsSep: "@",
        });
        expect(formatFloat(6000)).toBe("60@00!00");
    });

    test("extreme magnitudes", () => {
        allowTranslations();
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });

        expect(formatFloat(1e21)).not.toBe("1.00");
        expect(formatFloat(1e21)).toBe("1e+21");
        expect(formatFloat(1.5e21)).toBe("1.5e+21");
        expect(formatFloat(-1.5e21)).toBe("-1.5e+21");
        expect(formatFloat(123456789012.34)).toBe("123,456,789,012.34");

        expect(formatFloat(1.2e-7, { digits: [16, 12] })).toBe("0.000000120000");
        expect(formatFloat(1e-7, { digits: [16, 7] })).toBe("0.0000001");

        expect(formatFloat(1e21, { humanReadable: true })).toBe("1e+21");
        expect(formatFloat(1234567, { humanReadable: true, decimals: 2 })).toBe(
            "1.23M",
        );
    });

    test("humanReadable", () => {
        allowTranslations();
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });

        const options = { humanReadable: true };
        expect(formatFloat(1e18, options)).toBe("1E");
        expect(formatFloat(-1e18, options)).toBe("-1E");

        Object.assign(options, { decimals: 2, minIntegerDigits: 1 });
        expect(formatFloat(1020, options)).toBe("1.02k");
        expect(formatFloat(1002, options)).toBe("1.00k");
        expect(formatFloat(101, options)).toBe("101.00");
        expect(formatFloat(64.2, options)).toBe("64.20");
        expect(formatFloat(1020, options)).toBe("1.02k");
        expect(formatFloat(1e21, options)).toBe("1e+21");
        expect(formatFloat(1.0045e22, options)).toBe("1e+22");
        expect(formatFloat(1.012e43, options)).toBe("1.01e+43");
        expect(formatFloat(-1020, options)).toBe("-1.02k");
        expect(formatFloat(-1020, options)).toBe("-1.02k");
        expect(formatFloat(-1002, options)).toBe("-1.00k");
        expect(formatFloat(-101, options)).toBe("-101.00");
        expect(formatFloat(-64.2, options)).toBe("-64.20");
        expect(formatFloat(-1e21, options)).toBe("-1e+21");
        expect(formatFloat(-1.0045e22, options)).toBe("-1e+22");
        expect(formatFloat(-1.012e43, options)).toBe("-1.01e+43");
        expect(formatFloat(-0.0000001, options)).toBe("0.00");

        Object.assign(options, { decimals: 2, minIntegerDigits: 2 });
        expect(formatFloat(1020000, options)).toBe("1,020k");
        expect(formatFloat(10200000, options)).toBe("10.20M");
        expect(formatFloat(1.012e43, options)).toBe("1.01e+43");
        expect(formatFloat(-1020000, options)).toBe("-1,020k");
        expect(formatFloat(-10200000, options)).toBe("-10.20M");
        expect(formatFloat(-1.012e43, options)).toBe("-1.01e+43");

        Object.assign(options, { decimals: 3, minIntegerDigits: 1 });
        expect(formatFloat(1.0045e22, options)).toBe("1.005e+22");
        expect(formatFloat(-1.0045e22, options)).toBe("-1.004e+22");

        [
            { val: 2.35, decimals: 1, resFixed: "2.4", resHuman: "2.4" },
            { val: 2.55, decimals: 1, resFixed: "2.5", resHuman: "2.6" },
            { val: 2.925, decimals: 2, resFixed: "2.92", resHuman: "2.93" },
            { val: 1.925, decimals: 2, resFixed: "1.93", resHuman: "1.93" },
        ].forEach(({ val, decimals, resFixed, resHuman }) => {
            Object.assign(options, { decimals });
            const value = parseFloat(val);
            expect(value.toFixed(decimals)).toBe(resFixed);
            expect(formatFloat(value, options)).toBe(resHuman);
        });

        Object.assign(options, {
            humanReadable: false,
            digits: undefined,
            minDigits: undefined,
            minIntegerDigits: undefined,
        });
        expect(formatFloat(-0.0000001, options)).toBe("0.00");
    });
});

test("humanNumber reads a negative decimal exponent", () => {
    allowTranslations();
    patchWithCleanup(localization, {
        decimalPoint: ".",
        grouping: [3, 0],
        thousandsSep: ",",
    });
    expect(humanNumber(0.001, { decimals: 3 })).toBe("0.001");
    expect(humanNumber(0.5, { decimals: 1 })).toBe("0.5");
    expect(humanNumber(-0.25, { decimals: 2 })).toBe("-0.25");
    expect(humanNumber(0, { decimals: 0 })).toBe("0");
    expect(humanNumber(1e22, { decimals: 0 })).toBe("1e+22");
});

describe("minDigits and minIntegerDigits are distinct options", () => {
    test("minDigits pads decimals and never reaches humanNumber", () => {
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });
        expect(formatFloat(1234.5, { minDigits: 3 })).toBe("1,234.500");
        expect(formatFloat(1234.5, { minDigits: 3, humanReadable: true })).toBe("1k");
        expect(formatFloat(1500000, { minDigits: 3, humanReadable: true })).toBe("2M");
    });

    test("minIntegerDigits holds off the unit suffix", () => {
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });
        expect(humanNumber(1500000)).toBe("2M");
        expect(humanNumber(1500000, { minIntegerDigits: 3 })).toBe("1,500k");
        expect(formatFloat(1500000, { humanReadable: true, minIntegerDigits: 3 })).toBe(
            "1,500k",
        );
    });

    test("a field's min_display_digits no longer distorts the human format", () => {
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });
        const field = { type: "float", min_display_digits: 3 };
        expect(formatterFloat(1234.5, { field })).toBe("1,234.500");
        expect(formatterFloat(1234.5, { field, humanReadable: true })).toBe("1k");
    });
});

describe("minDigits never exceeds the precision the value was rounded to", () => {
    test("padding never outruns digits[1]", () => {
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });
        expect(formatFloat(12.5432, { digits: [16, 2], minDigits: 4 })).toBe("12.54");
        expect(formatFloat(12.5, { digits: [16, 2], minDigits: 4 })).toBe("12.50");
        expect(formatFloat(3.1239, { digits: [16, 2], minDigits: 6 })).toBe("3.12");
    });

    test("minDigits below digits[1] is unaffected", () => {
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });
        expect(formatFloat(3.1239, { digits: [15, 4], minDigits: 3 })).toBe("3.1239");
        expect(formatFloat(3.1, { digits: [15, 4], minDigits: 3 })).toBe("3.100");
        expect(formatFloat(3, { digits: [15, 3] })).toBe("3.000");
    });

    test("minDigits with no digits still caps at the computed precision", () => {
        patchWithCleanup(localization, {
            decimalPoint: ".",
            grouping: [3, 0],
            thousandsSep: ",",
        });
        expect(formatFloat(3.1, { minDigits: 8 })).toBe("3.100000");
        expect(formatFloat(3.1, { minDigits: 3 })).toBe("3.100");
    });
});
