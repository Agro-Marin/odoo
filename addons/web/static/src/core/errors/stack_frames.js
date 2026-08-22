// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";

/**
 * @typedef {{
 * functionName: string,
 * fileName: string,
 * lineNumber: number,
 * columnNumber: number,
 * }} StackFrame
 */

const V8_FRAME_RE = /^\s*at\s+(?:(.*?)\s+\()?(.+?):(\d+):(\d+)\)?\s*$/;
const GECKO_FRAME_RE = /^\s*(?:(.*?)@)?(.+?):(\d+):(\d+)\s*$/;

/**
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

const BASE64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const BASE64_VALUES = new Map([...BASE64_CHARS].map((c, i) => [c, i]));

/**
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
                        values.length = 0;
                        break;
                    }
                    value += (digit & 31) << shift;
                    if (digit & 32) {
                        shift += 5;
                    } else {
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
            }
        }
        lines.push(segments);
    }
    return lines;
}

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
     * @param {number} line
     * @param {number} column
     * @returns {{ source: string, line: number, column: number } | null}
     */
    originalPositionFor(line, column) {
        const segments = this.lines[line - 1];
        if (!segments || !segments.length) {
            return null;
        }
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

export function clearSourceMapCache() {
    consumerCache.clear();
}

const SOURCE_MAPPING_URL_RE = /\/\/# sourceMappingURL=(\S+)\s*$/;

/**
 * @param {string} scriptUrl
 * @returns {Promise<SourceMapConsumer | null>}
 */
function getConsumer(scriptUrl) {
    let promise = consumerCache.get(scriptUrl);
    if (!promise) {
        promise = (
            /** @returns {Promise<SourceMapConsumer | null>} */
            async () => {
                const scriptText = await (await browser.fetch(scriptUrl)).text();
                const directiveIndex = scriptText.lastIndexOf("//# sourceMappingURL=");
                const tail =
                    directiveIndex === -1 ? "" : scriptText.slice(directiveIndex);
                const match = SOURCE_MAPPING_URL_RE.exec(tail);
                if (!match) {
                    return null;
                }
                const scriptHref = new URL(scriptUrl, globalThis.location.href);
                const mapUrl = new URL(match[1], scriptHref).href;
                const map = await (await browser.fetch(mapUrl)).json();
                return new SourceMapConsumer(map);
            }
        )().catch(/** @returns {SourceMapConsumer | null} */ () => null);
        consumerCache.set(scriptUrl, promise);
    }
    return promise;
}

/**
 * @param {StackFrame[]} frames
 * @returns {Promise<StackFrame[]>}
 */
export async function mapFramesToSource(frames) {
    return Promise.all(
        frames.map(async (frame) => {
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
