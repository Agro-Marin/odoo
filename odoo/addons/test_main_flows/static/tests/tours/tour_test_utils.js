export function assertEqual(actual, expected, msg = "") {
    if (actual !== expected) {
        const description = msg ? ` ${msg}` : "";
        throw new Error(`Assert failed: expected: ${expected} ; got: ${actual}.${description}`);
    }
}
