//----------------------------------------------------------------------------------------------------------------------
// Assertion helpers for tours
//----------------------------------------------------------------------------------------------------------------------
export class Asserts {
    //------------------------------------------------------------------------------------------------------------------
    // Helpers
    //------------------------------------------------------------------------------------------------------------------
    static getCount(target, selector) {
        return document.querySelector(target).querySelectorAll(selector).length;
    }
    static getDOMCount(selector) {
        return document.querySelectorAll(selector).length;
    }
    static check(condition, success, error) {
        condition ? Asserts.success(success) : Asserts.error(error);
    }
    static success(message) {
        return console.info(`SUCCESS: ${message}`);
    }
    static error(message) {
        throw new Error(`FAIL: ${message}`);
    }

    //------------------------------------------------------------------------------------------------------------------
    // Asserts
    //------------------------------------------------------------------------------------------------------------------
    static isTrue(actual) {
        Asserts.check(actual, `${actual} is true`, `${actual} is not true`);
    }
    static isFalse(actual) {
        Asserts.check(!actual, `${actual} is false`, `${actual} is not false`);
    }
    static isEqual(actual, expected) {
        Asserts.check(
            // eslint-disable-next-line eqeqeq -- isStrictEqual below is the === form; this one is deliberately loose
            actual == expected,
            `${actual} is equal to expected ${expected}`,
            `${actual} is not equal to expected ${expected}`,
        );
    }
    static isStrictEqual(actual, expected) {
        Asserts.check(
            actual === expected,
            `${actual} is strictly equal to expected ${expected}`,
            `${actual} is not strictly equal to expected ${expected}`,
        );
    }
    static contains(target, selector) {
        const count = Asserts.getCount(target, selector);
        Asserts.check(
            count > 0,
            `There is at least one ${selector} in ${target}`,
            `There should be at least one ${selector} in ${target} but there is ${count}`,
        );
    }
    static containsNone(target, selector) {
        const count = Asserts.getCount(target, selector);
        Asserts.check(
            count === 0,
            `There is no ${selector} in ${target}`,
            `There should be no ${selector} in ${target} but there is ${count}`,
        );
    }
    static containsNumber(target, selector, number) {
        const count = Asserts.getCount(target, selector);
        Asserts.check(
            count === number,
            `There is the correct number (${number}) of ${selector} in ${target}`,
            `There should be at ${number} ${selector} in ${target} but there is ${count}`,
        );
    }
    static DOMContains(selector) {
        const count = Asserts.getDOMCount(selector);
        Asserts.check(
            count > 0,
            `There is at least one ${selector} in the DOM`,
            `There should be at least one ${selector} in the DOM but there is ${count}`,
        );
    }
    static DOMContainsNone(selector) {
        const count = Asserts.getDOMCount(selector);
        Asserts.check(
            count === 0,
            `There is no ${selector} in the DOM`,
            `There should be 0 ${selector} in the DOM but there is ${count}`,
        );
    }
    static DOMContainsNumber(selector, number) {
        const count = Asserts.getDOMCount(selector);
        Asserts.check(
            Asserts.getDOMCount(selector) === number,
            `There is the correct number (${number}) of ${selector} in the DOM`,
            `There should be ${number} ${selector} in the DOM but there is ${count}`,
        );
    }
    static hasClass(selector, classname) {
        Asserts.check(
            document.querySelector(selector).classList.contains(classname),
            `${selector} has class ${classname}`,
            `${selector} should have class ${classname} but hasn't`,
        );
    }
}
