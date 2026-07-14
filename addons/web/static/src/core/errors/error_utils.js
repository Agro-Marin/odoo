// @ts-check
/** @odoo-module native */

/** @module @web/core/errors/error_utils - Traceback formatting, source-map annotation, and error chain utilities */

// NB: relative imports need the explicit extension: esbuild resolves without
// it, but in ?debug=assets mode the BROWSER resolves this raw file's imports,
// requests the extensionless URL, 404s, and the failed import takes down the
// whole module graph (white screen on every debug=assets page).
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
    // preventDefault must be called synchronously or the browser logs an
    // unannotated traceback (annotation is async). So we always preventDefault,
    // then rethrow after annotating — re-triggering error handling, which then
    // hits the early-return above since annotatedTraceback is now cached.
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
    // Ensure error name/message are present regardless of the browser's stack formatting.
    // Stack example:
    // Error: Mock: Can't write value
    //     _onOpenFormView@http://localhost:8069/web/content/425-baf33f1/web.assets.js:1064:30
    //     ...
    const descriptionLine = `${errorName}: ${error.message}`;
    if (stack && stack.split("\n")[0].trim() !== descriptionLine) {
        // avoid having the description line twice if already present
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
    // In Firefox, the error stack generated by anonymous code (example: invalid
    // code in a template) carries a " line N > Function:M" suffix the frame
    // parser cannot align. Normalize a local copy to avoid mutating the error.
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
        // firefox traceback have an empty line at the end
        lines.splice(-1);
    }

    let lineIndex = 0;
    let frameIndex = 0;
    while (frameIndex < frames.length && lineIndex < lines.length) {
        const line = lines[lineIndex];
        // skip lines that have no location information as they don't correspond to a frame
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
