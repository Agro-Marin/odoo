// @ts-check
/** @odoo-module native */

/** @module @web/core/errors/stack_frames - Native error-stack parsing and sourcemap resolution */

/**
 * Replaces the vendored stacktrace.js UMD build (the last consumer of the
 * ``loadJS`` + global pattern in core error handling).  Two independent
 * halves:
 *
 *   * {@link parseStackFrames} — parse ``error.stack`` text into structured
 *     frames.  Handles the V8 format (``at func (url:line:col)`` /
 *     ``at url:line:col``) and the Firefox/Safari format
 *     (``func@url:line:col``).
 *
 *   * {@link mapFramesToSource} — best-effort sourcemap resolution: when a
 *     frame's script advertises a ``//# sourceMappingURL=`` (the esbuild
 *     ``linked`` mode emits one pointing at the sibling ``.map``
 *     attachment), decode the map and rewrite the frame to the original
 *     file/line.  Scripts without a map (the production default) leave
 *     their frames untouched — same graceful degradation stacktrace.js
 *     had.  All fetches go through the HTTP cache; bundle URLs are
 *     content-addressed and immutable, so re-requesting the script text
 *     costs a disk-cache read, not a network round-trip.
 */

/**
 * @typedef {{
 *     functionName: string,
 *     fileName: string,
 *     lineNumber: number,
 *     columnNumber: number,
 * }} StackFrame
 */

// V8:      "    at fn (https://x/y.js:1:2)" | "    at https://x/y.js:1:2"
//          (optional "async " / "new " prefixes on the function name)
const V8_FRAME_RE = /^\s*at\s+(?:(.*?)\s+\()?(.+?):(\d+):(\d+)\)?\s*$/;
// FF/Safari: "fn@https://x/y.js:1:2" | "@https://x/y.js:1:2" | "https://x/y.js:1:2"
const GECKO_FRAME_RE = /^\s*(?:(.*?)@)?(.+?):(\d+):(\d+)\s*$/;

/**
 * Parse an ``error.stack`` string into structured frames.  Lines carrying
 * no ``:line:col`` location (the message line, ``[native code]`` frames)
 * are skipped — mirroring the alignment rule ``annotateTraceback`` uses.
 *
 * @param {string} stack
 * @returns {StackFrame[]}
 */
export function parseStackFrames(stack) {
    const frames = [];
    for (const line of (stack || "").split("\n")) {
        const match = V8_FRAME_RE.exec(line) || GECKO_FRAME_RE.exec(line);
        if (!match) {
            continue;
        }
        const [, functionName, fileName, lineNumber, columnNumber] = match;
        if (fileName.includes("[native code]")) {
            continue;
        }
        frames.push({
            functionName: functionName || "<anonymous>",
            fileName,
            lineNumber: parseInt(lineNumber, 10),
            columnNumber: parseInt(columnNumber, 10),
        });
    }
    return frames;
}

// ── Sourcemap consumer ─────────────────────────────────────────────
//
// Deliberately minimal: decode the ``mappings`` VLQ into per-generated-line
// segment arrays and binary-search them.  No ``sourcesContent`` handling,
// no section-indexed maps — esbuild emits neither.

const BASE64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const BASE64_VALUES = new Map([...BASE64_CHARS].map((c, i) => [c, i]));

/**
 * Decode one sourcemap ``mappings`` string into an array (indexed by
 * generated line) of segment arrays ``[genCol, srcIdx, origLine, origCol]``
 * sorted by generated column.  Fields are delta-encoded: generated column
 * resets per line, the other three run across the whole string.
 *
 * @param {string} mappings
 * @returns {number[][][]}
 */
export function decodeMappings(mappings) {
    const lines = [];
    let srcIdx = 0;
    let origLine = 0;
    let origCol = 0;
    for (const lineText of mappings.split(";")) {
        /** @type {number[][]} */
        const segments = [];
        let genCol = 0;
        if (lineText) {
            for (const segText of lineText.split(",")) {
                const values = [];
                let value = 0;
                let shift = 0;
                for (const char of segText) {
                    const digit = BASE64_VALUES.get(char);
                    if (digit === undefined) {
                        // Corrupt segment: drop it rather than misalign.
                        values.length = 0;
                        break;
                    }
                    value += (digit & 31) << shift;
                    if (digit & 32) {
                        shift += 5;
                    } else {
                        // Sign bit is the LSB of the assembled value.
                        values.push(value & 1 ? -(value >>> 1) : value >>> 1);
                        value = 0;
                        shift = 0;
                    }
                }
                if (values.length < 1) {
                    continue;
                }
                genCol += values[0];
                if (values.length >= 4) {
                    srcIdx += values[1];
                    origLine += values[2];
                    origCol += values[3];
                    segments.push([genCol, srcIdx, origLine, origCol]);
                }
                // 1-field segments (generated-only) carry no source info —
                // nothing to look up, skip. 5th field (name index) unused.
            }
        }
        lines.push(segments);
    }
    return lines;
}

/**
 * A decoded sourcemap bound to its ``sources`` list.
 */
class SourceMapConsumer {
    /**
     * @param {{ sources: string[], mappings: string, sourceRoot?: string }} map
     */
    constructor(map) {
        this.sources = (map.sources || []).map((s) =>
            map.sourceRoot ? `${map.sourceRoot}${s}` : s,
        );
        this.lines = decodeMappings(map.mappings || "");
    }

    /**
     * Map a 1-based generated position to the original source, or ``null``
     * when the position precedes every mapping on its line.
     *
     * @param {number} line 1-based generated line
     * @param {number} column 1-based generated column
     * @returns {{ source: string, line: number, column: number } | null}
     */
    originalPositionFor(line, column) {
        const segments = this.lines[line - 1];
        if (!segments || !segments.length) {
            return null;
        }
        // Binary search: last segment whose generated column <= column.
        const genCol = column - 1;
        let lo = 0;
        let hi = segments.length - 1;
        if (segments[0][0] > genCol) {
            return null;
        }
        while (lo < hi) {
            const mid = (lo + hi + 1) >> 1;
            if (segments[mid][0] <= genCol) {
                lo = mid;
            } else {
                hi = mid - 1;
            }
        }
        const [, srcIdx, origLine, origCol] = segments[lo];
        const source = this.sources[srcIdx];
        if (source === undefined) {
            return null;
        }
        return { source, line: origLine + 1, column: origCol + 1 };
    }
}

/** @type {Map<string, Promise<SourceMapConsumer | null>>} */
const consumerCache = new Map();

/** Test seam: drop the per-URL consumer cache. */
export function clearSourceMapCache() {
    consumerCache.clear();
}

const SOURCE_MAPPING_URL_RE = /\/\/# sourceMappingURL=(\S+)\s*$/;

/**
 * Resolve the sourcemap consumer for one script URL, or ``null`` when the
 * script has no (reachable, parsable) map.  Cached per URL — error dialogs
 * repeatedly annotate frames from the same handful of bundles.
 *
 * @param {string} scriptUrl
 * @returns {Promise<SourceMapConsumer | null>}
 */
function getConsumer(scriptUrl) {
    let promise = consumerCache.get(scriptUrl);
    if (!promise) {
        promise = (async () => {
            const scriptText = await (await fetch(scriptUrl)).text();
            // Last directive wins (matches browser behavior); scan the tail
            // only — esbuild puts the directive on the final line.
            const tail = scriptText.slice(-1024);
            const match = SOURCE_MAPPING_URL_RE.exec(tail);
            if (!match) {
                return null;
            }
            // Resolve relative to the script URL, itself resolved against
            // the document (frame fileNames may be path-absolute).
            const scriptHref = new URL(scriptUrl, globalThis.location.href);
            const mapUrl = new URL(match[1], scriptHref).href;
            const map = await (await fetch(mapUrl)).json();
            return new SourceMapConsumer(map);
        })().catch(
            () =>
                // Unreachable script, no directive, cross-origin block, corrupt
                // map: annotation degrades to raw frames, never an error.
                null,
        );
        consumerCache.set(scriptUrl, promise);
    }
    return promise;
}

/**
 * Rewrite frames to their original source positions where a sourcemap is
 * available; frames without one pass through unchanged.
 *
 * @param {StackFrame[]} frames
 * @returns {Promise<StackFrame[]>}
 */
export async function mapFramesToSource(frames) {
    return Promise.all(
        frames.map(async (frame) => {
            // Only same-document http(s)/path script URLs can carry a map
            // we may fetch (data:, blob:, <anonymous> cannot).
            if (!/^(https?:)?\//.test(frame.fileName)) {
                return frame;
            }
            const consumer = await getConsumer(frame.fileName);
            const position = consumer?.originalPositionFor(
                frame.lineNumber,
                frame.columnNumber,
            );
            if (!position) {
                return frame;
            }
            return {
                functionName: frame.functionName,
                fileName: position.source,
                lineNumber: position.line,
                columnNumber: position.column,
            };
        }),
    );
}
