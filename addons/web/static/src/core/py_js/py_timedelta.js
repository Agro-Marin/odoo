// @ts-check
/** @odoo-module native */

import { bindArgs } from "./py_args.js";

/** @type {Record<string, bigint>} */
const US_PER_UNIT = {
    weeks: 604800000000n,
    days: 86400000000n,
    hours: 3600000000n,
    minutes: 60000000n,
    seconds: 1000000n,
    milliseconds: 1000n,
    microseconds: 1n,
};

const TIME_DELTA_KEYS = Object.keys(US_PER_UNIT);

/**
 * @param {bigint} a
 * @param {bigint} b
 * @returns {[bigint, bigint]}
 */
function bigDivMod(a, b) {
    let quotient = a / b;
    let remainder = a - quotient * b;
    if (remainder !== 0n && remainder < 0n !== b < 0n) {
        quotient -= 1n;
        remainder += b;
    }
    return [quotient, remainder];
}

/**
 * @param {number} x
 * @returns {[number, number]}
 */
function modf(x) {
    const whole = Math.trunc(x);
    return [x - whole, whole];
}

/**
 * @param {number} x
 * @returns {number}
 */
function roundHalfEven(x) {
    const whole = Math.floor(x);
    const frac = x - whole;
    if (frac > 0.5) {
        return whole + 1;
    }
    if (frac < 0.5) {
        return whole;
    }
    return whole % 2 === 0 ? whole : whole + 1;
}

export class PyTimeDelta {
    /**
     * @param {...any} args
     * @returns {PyTimeDelta}
     */
    static create(...args) {
        const namedArgs = bindArgs(
            args,
            [
                "days",
                "seconds",
                "microseconds",
                "milliseconds",
                "minutes",
                "hours",
                "weeks",
            ],
            "timedelta",
        );

        let total = 0n;
        let leftover = 0;
        for (const key of TIME_DELTA_KEYS) {
            const value = namedArgs[key] || 0;
            const factor = US_PER_UNIT[key];
            if (Number.isInteger(value)) {
                total += BigInt(value) * factor;
            } else {
                const [frac, whole] = modf(value);
                total += BigInt(whole) * factor;
                leftover += frac * Number(factor);
            }
        }

        if (leftover) {
            let wholeUs = roundHalfEven(leftover);
            if (Math.abs(wholeUs - leftover) === 0.5) {
                const totalIsOdd = Number(((total % 2n) + 2n) % 2n);
                wholeUs = 2 * Math.round((leftover + totalIsOdd) * 0.5) - totalIsOdd;
            }
            total += BigInt(wholeUs);
        }

        const [totalSeconds, microsecond] = bigDivMod(total, 1000000n);
        const [day, second] = bigDivMod(totalSeconds, 86400n);
        return new PyTimeDelta(Number(day), Number(second), Number(microsecond));
    }

    /**
     * @param {number} days
     * @param {number} seconds
     * @param {number} microseconds
     */
    constructor(days, seconds, microseconds) {
        this.days = days;
        this.seconds = seconds;
        this.microseconds = microseconds;
    }

    /**
     * @param {PyTimeDelta} other
     * @returns {PyTimeDelta}
     */
    add(other) {
        return PyTimeDelta.create({
            days: this.days + other.days,
            seconds: this.seconds + other.seconds,
            microseconds: this.microseconds + other.microseconds,
        });
    }

    /**
     * @returns {number}
     */
    toMicroseconds() {
        return (this.days * 24 * 3600 + this.seconds) * 1e6 + this.microseconds;
    }

    /**
     * @param {number} n
     * @returns {PyTimeDelta}
     */
    divide(n) {
        return PyTimeDelta.create({
            microseconds: Math.floor(this.toMicroseconds() / n),
        });
    }

    /**
     * @param {number} n
     * @returns {PyTimeDelta}
     */
    divideTrue(n) {
        return PyTimeDelta.create({
            microseconds: Math.round(this.toMicroseconds() / n),
        });
    }

    /**
     * @param {any} other
     * @returns {boolean}
     */
    isEqual(other) {
        if (!(other instanceof PyTimeDelta)) {
            return false;
        }
        return (
            this.days === other.days &&
            this.seconds === other.seconds &&
            this.microseconds === other.microseconds
        );
    }

    /** @returns {boolean} */
    isTrue() {
        return this.days !== 0 || this.seconds !== 0 || this.microseconds !== 0;
    }

    /**
     * @param {number} n
     * @returns {PyTimeDelta}
     */
    multiply(n) {
        return PyTimeDelta.create({
            days: n * this.days,
            seconds: n * this.seconds,
            microseconds: n * this.microseconds,
        });
    }

    /** @returns {PyTimeDelta} */
    negate() {
        return PyTimeDelta.create({
            days: -this.days,
            seconds: -this.seconds,
            microseconds: -this.microseconds,
        });
    }

    /**
     * @param {PyTimeDelta} other
     * @returns {PyTimeDelta}
     */
    subtract(other) {
        return PyTimeDelta.create({
            days: this.days - other.days,
            seconds: this.seconds - other.seconds,
            microseconds: this.microseconds - other.microseconds,
        });
    }

    /** @returns {number} */
    total_seconds() {
        return this.days * 86400 + this.seconds + this.microseconds / 1000000;
    }

    /**
     * @returns {string}
     */
    toString() {
        const mm = Math.floor(this.seconds / 60);
        const ss = this.seconds % 60;
        const hh = Math.floor(mm / 60);
        const m = mm % 60;
        let s = `${hh}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
        if (this.days) {
            const plural = Math.abs(this.days) !== 1 ? "s" : "";
            s = `${this.days} day${plural}, ${s}`;
        }
        if (this.microseconds) {
            s = `${s}.${String(this.microseconds).padStart(6, "0")}`;
        }
        return s;
    }

    /**
     * @returns {number}
     */
    valueOf() {
        return this.total_seconds();
    }
}
