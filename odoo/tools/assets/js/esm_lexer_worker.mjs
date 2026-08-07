import { init, parse } from "es-module-lexer";
import { createInterface } from "node:readline";

await init;

const rl = createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line) => {
    let req;
    try {
        req = JSON.parse(line);
    } catch {
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
