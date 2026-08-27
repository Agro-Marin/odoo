/** @odoo-module */

import { isNil, stringToNumber } from "../hoot_utils.js";

const {
    Math,
    Number: { isNaN: $isNaN, parseFloat: $parseFloat },
    Object: { defineProperties: $defineProperties },
} = globalThis;
const { floor: $floor, random: $random } = Math;

/**
 * @param {unknown} [seed]
 */
function toValidSeed(seed) {
    if (isNil(seed)) {
        return generateSeed();
    }
    const nSeed = $parseFloat(seed);
    return $isNaN(nSeed) ? stringToNumber(nSeed) : nSeed;
}

const DEFAULT_SEED = 1e16;

export function generateSeed() {
    return $floor($random() * 1e16);
}

/**
 * @param {number} seed
 */
export function makeSeededRandom(seed) {
    function random() {
        state ^= (state << 13) >>> 0;
        state ^= (state >>> 17) >>> 0;
        state ^= (state << 5) >>> 0;

        return ((state >>> 0) & 0x7fffffff) / 0x7fffffff;
    }

    let state = seed;

    $defineProperties(random, {
        seed: {
            get() {
                return seed;
            },
            set(value) {
                seed = toValidSeed(value);
                state = seed;
            },
        },
    });

    return random;
}

export const internalRandom = makeSeededRandom(DEFAULT_SEED);
