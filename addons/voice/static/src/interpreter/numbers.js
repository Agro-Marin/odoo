// @ts-check
/** @odoo-module native */

import { normalize } from "@web/core/l10n/utils";

/** @type {Record<string, number>} */
const UNITS = {
    cero: 0,
    zero: 0,
    un: 1,
    uno: 1,
    una: 1,
    one: 1,
    a: 1,
    dos: 2,
    two: 2,
    tres: 3,
    three: 3,
    cuatro: 4,
    four: 4,
    cinco: 5,
    five: 5,
    seis: 6,
    six: 6,
    siete: 7,
    seven: 7,
    ocho: 8,
    eight: 8,
    nueve: 9,
    nine: 9,
    diez: 10,
    ten: 10,
    once: 11,
    eleven: 11,
    doce: 12,
    twelve: 12,
    trece: 13,
    thirteen: 13,
    catorce: 14,
    fourteen: 14,
    quince: 15,
    fifteen: 15,
    dieciseis: 16,
    sixteen: 16,
    diecisiete: 17,
    seventeen: 17,
    dieciocho: 18,
    eighteen: 18,
    diecinueve: 19,
    nineteen: 19,
    veinte: 20,
    twenty: 20,
    veintiun: 21,
    veintiuno: 21,
    veintiuna: 21,
    veintidos: 22,
    veintitres: 23,
    veinticuatro: 24,
    veinticinco: 25,
    veintiseis: 26,
    veintisiete: 27,
    veintiocho: 28,
    veintinueve: 29,
    treinta: 30,
    thirty: 30,
    cuarenta: 40,
    forty: 40,
    cincuenta: 50,
    fifty: 50,
    sesenta: 60,
    sixty: 60,
    setenta: 70,
    seventy: 70,
    ochenta: 80,
    eighty: 80,
    noventa: 90,
    ninety: 90,
    cien: 100,
    ciento: 100,
    doscientos: 200,
    doscientas: 200,
    trescientos: 300,
    trescientas: 300,
    cuatrocientos: 400,
    cuatrocientas: 400,
    quinientos: 500,
    quinientas: 500,
    seiscientos: 600,
    seiscientas: 600,
    setecientos: 700,
    setecientas: 700,
    ochocientos: 800,
    ochocientas: 800,
    novecientos: 900,
    novecientas: 900,
};

const HUNDRED = new Set(["hundred", "hundreds"]);
const THOUSAND = new Set(["mil", "thousand", "thousands"]);
const MILLION = new Set(["millon", "millones", "million", "millions"]);
const JOINERS = new Set(["y", "and"]);
const MINUS = new Set(["menos", "minus", "negativo", "negative"]);
const POINT = new Set(["punto", "coma", "point", "dot"]);

/**
 * @param {string[]} words normalized
 * @returns {number | null}
 */
function parseInteger(words) {
    let total = 0;
    let current = 0;
    let seen = false;
    for (const word of words) {
        if (/^\d+$/.test(word)) {
            current += Number(word);
        } else if (word in UNITS) {
            current += UNITS[word];
        } else if (HUNDRED.has(word)) {
            current = (current || 1) * 100;
        } else if (THOUSAND.has(word)) {
            total += (current || 1) * 1000;
            current = 0;
        } else if (MILLION.has(word)) {
            total += (current || 1) * 1_000_000;
            current = 0;
        } else if (JOINERS.has(word) && seen) {
            continue;
        } else {
            return null;
        }
        seen = true;
    }
    return seen ? total + current : null;
}

/**
 * "cinco", "treinta y cinco", "dos mil quinientos", "five point five",
 * "12.5", "-3": what a speech recogniser writes for a number.
 *
 * @param {string} text
 * @returns {number | null}
 */
export function parseSpokenNumber(text) {
    const compact = text.trim().replace(/\s+/g, "");
    if (/^-?\d+([.,]\d+)?$/.test(compact)) {
        return Number(compact.replace(",", "."));
    }
    const words = normalize(text)
        .split(/[^\p{L}\p{N}]+/u)
        .filter(Boolean);
    let sign = 1;
    if (words.length && MINUS.has(words[0])) {
        sign = -1;
        words.shift();
    }
    const pointIndex = words.findIndex((word) => POINT.has(word));
    if (pointIndex === -1) {
        const integer = parseInteger(words);
        return integer === null ? null : sign * integer;
    }
    const integer = pointIndex ? parseInteger(words.slice(0, pointIndex)) : 0;
    const fractionWords = words.slice(pointIndex + 1);
    if (integer === null || !fractionWords.length) {
        return null;
    }
    let digits = "";
    for (const word of fractionWords) {
        const value = /^\d+$/.test(word) ? Number(word) : UNITS[word];
        if (value === undefined || value > 99) {
            return null;
        }
        digits += String(value);
    }
    return sign * Number(`${integer}.${digits}`);
}
