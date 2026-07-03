/**
 * Persistent es-module-lexer worker for the assets pipeline.
 *
 * Protocol: line-delimited JSON over stdio, strict request/response
 * ping-pong (the Python side — ``odoo.tools.assets.esm_lexer`` — never
 * pipelines).  Request: ``{"id": n, "src": "<js source>"}``.  Response:
 *
 *     {"id": n, "ok": true,
 *      "names": [..named exports..], "hasDefault": bool,
 *      "starFrom": [..raw `export * from` specifiers..],
 *      "imports": [{"n": "<specifier>", "kind": "named|default|star|side"}]}
 *
 * or ``{"id": n, "ok": false, "error": "..."}`` when the source does not
 * lex (the Python side falls back to its regex extractor).
 *
 * Notes mirroring the Python regex path this replaces:
 *   - `export * as ns from "x"` contributes the single name ``ns`` (via
 *     the exports array); it is NOT a ``starFrom`` entry.
 *   - `export {x} from "y"` / `export * from "y"` statements are NOT
 *     import records — bridge discovery only follows `import` forms.
 *   - Dynamic ``import(...)`` is skipped (d >= 0), as is any statement
 *     with a computed/absent specifier.
 */
import { createInterface } from "node:readline";
import { init, parse } from "es-module-lexer";

await init;

const rl = createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line) => {
    /** @type {{id?: number, src?: string}} */
    let req;
    try {
        req = JSON.parse(line);
    } catch {
        // Unparseable request: nothing to correlate a response to; the
        // client's read will time out and it will fall back.
        return;
    }
    const out = { id: req.id };
    try {
        const src = String(req.src ?? "");
        const [imports, exports] = parse(src);
        const names = [];
        let hasDefault = false;
        for (const e of exports) {
            if (e.n === "default") {
                hasDefault = true;
            } else if (e.n) {
                names.push(e.n);
            }
        }
        const starFrom = [];
        const importRecords = [];
        for (const i of imports) {
            if (i.d >= 0 || !i.n) {
                continue;
            }
            const stmt = src.slice(i.ss, i.se);
            if (/^\s*export\b/.test(stmt)) {
                if (/^\s*export\s*\*\s*from\b/.test(stmt)) {
                    starFrom.push(i.n);
                }
                continue;
            }
            let kind = "named";
            if (/^\s*import\s*\*/.test(stmt)) {
                kind = "star";
            } else if (/^\s*import\s+[\w$]/.test(stmt)) {
                kind = "default";
            } else if (/^\s*import\s*["']/.test(stmt)) {
                kind = "side";
            }
            importRecords.push({ n: i.n, kind });
        }
        out.ok = true;
        out.names = names;
        out.hasDefault = hasDefault;
        out.starFrom = starFrom;
        out.imports = importRecords;
    } catch (err) {
        out.ok = false;
        out.error = String((err && err.message) || err);
    }
    process.stdout.write(JSON.stringify(out) + "\n");
});
