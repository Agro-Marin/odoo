// @ts-check
/** @odoo-module native */

/** @module @web/core/errors/error_utils - Traceback formatting, source-map annotation, and error chain utilities */

import { mapFramesToSource, parseStackFrames } from "./stack_frames.js";

/** @typedef {import("./uncaught_errors").UncaughtError} UncaughtError */

/**
 * An Error with optional custom properties used by the Odoo error pipeline.
 * `annotatedTraceback` caches the annotated traceback string once computed.
 * `errorEvent` holds the original browser ErrorEvent/PromiseRejectionEvent.
 *
 * @typedef {Error & {
 *     annotatedTraceback?: string,
 *     errorEvent?: ErrorEvent | PromiseRejectionEvent,
 * }} AnnotatedError
 */

/**
 * @param {UncaughtError} uncaughtError
 * @param {Error} originalError
 * @returns {string}
 */
function combineErrorNames(uncaughtError, originalError) {
    const originalErrorName = getErrorTechnicalName(originalError);
    const uncaughtErrorName = getErrorTechnicalName(uncaughtError);
    if (originalErrorName === Error.name) {
        return uncaughtErrorName;
    } else {
        return `${uncaughtErrorName} > ${originalErrorName}`;
    }
}

/**
 * Returns the full traceback for an error chain based on error causes
 *
 * @param {Error} error
 * @returns {string}
 */
export function fullTraceback(error) {
    let traceback = formatTraceback(error);
    const seen = new Set([error]);
    let current = /** @type {any} */ (error.cause);
    while (current && !seen.has(current)) {
        seen.add(current);
        traceback += `\n\nCaused by: ${
            current instanceof Error ? formatTraceback(current) : current
        }`;
        current = current.cause;
    }
    return traceback;
}

/**
 * Returns the full annotated traceback for an error chain based on error causes
 *
 * @param {AnnotatedError} error
 * @returns {Promise<string>}
 */
export async function fullAnnotatedTraceback(error) {
    if (error.annotatedTraceback) {
        return error.annotatedTraceback;
    }
    if (error.errorEvent) {
        error.errorEvent.preventDefault();
    }
    let traceback;
    try {
        traceback = await annotateTraceback(error);
        const seen = new Set([error]);
        let current = /** @type {any} */ (error.cause);
        while (current && !seen.has(current)) {
            seen.add(current);
            traceback += `\n\nCaused by: ${
                current instanceof Error ? await annotateTraceback(current) : current
            }`;
            current = current.cause;
        }
    } catch (e) {
        console.warn(
            "Failed to annotate traceback for error:",
            error,
            "failure reason:",
            e,
        );
        traceback = fullTraceback(error);
    }
    error.annotatedTraceback = traceback;
    if (error.errorEvent) {
        throw error;
    }
    return traceback;
}

/**
 * @param {UncaughtError} uncaughtError
 * @param {Error} originalError
 * @param {boolean} annotated
 * @returns {Promise<void>}
 */
export async function completeUncaughtError(
    uncaughtError,
    originalError,
    annotated = false,
) {
    uncaughtError.name = combineErrorNames(uncaughtError, originalError);
    if (annotated) {
        uncaughtError.traceback = await fullAnnotatedTraceback(originalError);
    } else {
        uncaughtError.traceback = fullTraceback(originalError);
    }
    if (originalError.message) {
        uncaughtError.message = `${uncaughtError.message} > ${originalError.message}`;
    }
    uncaughtError.cause = originalError;
}

/**
 * @param {Error} error
 * @returns {string}
 */
export function getErrorTechnicalName(error) {
    return error.name !== Error.name ? error.name : error.constructor.name;
}

/**
 * Format the traceback of an error, adding the error message if the
 * browser's stack doesn't already include it (Chrome does by default).
 *
 * @param {Error} error
 * @returns {string}
 */
function formatTraceback(error) {
    const stack = error.stack ?? "";
    const errorName = getErrorTechnicalName(error);
    const descriptionLine = `${errorName}: ${error.message}`;
    if (stack && stack.split("\n")[0].trim() !== descriptionLine) {
        return `${descriptionLine}\n${stack}`.replace(/\n/g, "\n    ");
    }
    return stack || descriptionLine;
}

/**
 * Annotate a traceback with source-mapped file/line info (async: fetches
 * sourcemaps for each script involved in the error).
 *
 * @param {Error} error
 * @returns {Promise<string>}
 */
export async function annotateTraceback(error) {
    const traceback = formatTraceback(error);
    const stack = (error.stack ?? "").replace(/ line (\d*) > (Function):(\d*)/g, `:$1`);
    let frames;
    try {
        frames = await mapFramesToSource(parseStackFrames(stack));
    } catch (e) {
        console.warn("The following error could not be annotated:", error, e);
        return traceback;
    }
    const lines = traceback.split("\n");
    if (lines.at(-1)?.trim() === "") {
        lines.splice(-1);
    }

    let lineIndex = 0;
    let frameIndex = 0;
    while (frameIndex < frames.length && lineIndex < lines.length) {
        const line = lines[lineIndex];
        if (!/:\d+:\d+\)?$/.test(line)) {
            lineIndex++;
            continue;
        }
        const frame = frames[frameIndex];
        const info = ` (${frame.fileName}:${frame.lineNumber})`;
        lines[lineIndex] = line + info;
        lineIndex++;
        frameIndex++;
    }
    return lines.join("\n");
}
