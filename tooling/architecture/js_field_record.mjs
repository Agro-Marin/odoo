/**
 * What each field widget reaches on `props.record`, for `js_field_record_surface.py`.
 *
 * `standardFieldProps` is four keys, and one of them is `record: { type: Object }`
 * — a live `RelationalRecord`, 83 own members before anything inherited. Every
 * field widget in the fork gets all of it, and nothing states which parts are
 * the contract.
 *
 * WHY THIS IS AN AST PASS
 *
 * A `grep -o 'record\.[a-z]*'` over the widget files is what produced the first
 * measurement, and it was wrong in two directions at once:
 *
 *   - it swept identifiers named `record` that are NOT `props.record` — loop
 *     variables over x2many rows, a kanban card's record, a callback parameter
 *     — inflating `record.data` by roughly a quarter;
 *   - it swept test fixtures, so `record.foo`, `record.int_field` and
 *     `record.bar` appeared as members of `RelationalRecord`.
 *
 * So the binding is resolved instead: only a member read on `this.props.record`,
 * on `props.record`, or on a local provably aliased to one of them is counted.
 * Anything else named `record` is reported separately as `unresolved` rather
 * than guessed at — a read the analysis cannot attribute is not evidence.
 *
 * WHAT IS EMITTED, per file:
 *
 *   isWidget    — declares `standardFieldProps` in its `static props`
 *   members     — members reached on the resolved `props.record`, whether by
 *                 `record.X` or by destructuring `const { X } = record`
 *   ownValue    — `record.data[props.name]`-shaped reads: the widget's OWN field
 *   siblings    — `record.data.someLiteral` reads: ANOTHER field of the record
 *   propSiblings— `record.data[props.someField]`: another field, named by an option
 *   dynamic     — `record.data[expr]` reads, where the key is not decidable
 *   unresolved  — reads on a bare `record` that could not be tied to props
 *
 * The split matters because it is the whole question. A widget that only ever
 * reads its own value and writes it back needs a value and a setter. A widget
 * that names a sibling field needs the record, and no narrowing will change
 * that.
 */
import { readFileSync } from "node:fs";
import * as espree from "espree";

const PARSE = { ecmaVersion: "latest", sourceType: "module", loc: true };

function walk(node, fn) {
    if (!node || typeof node.type !== "string") {
        return;
    }
    fn(node);
    for (const key of Object.keys(node)) {
        if (key === "loc" || key === "range" || key === "parent") {
            continue;
        }
        const child = node[key];
        if (Array.isArray(child)) {
            child.forEach((c) => walk(c, fn));
        } else if (child && typeof child.type === "string") {
            walk(child, fn);
        }
    }
}

/**
 * Is `node` the `props` object — `this.props`, or a bare `props` parameter?
 *
 * Both forms are live in the tree. Accepting only the `this.props` form drops
 * every widget that destructures its props or takes them as an argument, which
 * is an *under*-count and therefore the quiet kind: the surface looks narrower
 * than it is and the gate passes.
 */
function isPropsObject(node) {
    if (node?.type === "Identifier") {
        return node.name === "props";
    }
    return (
        node?.type === "MemberExpression" &&
        !node.computed &&
        node.property?.name === "props"
    );
}

/** `this.props.record` or `props.record`. */
function isPropsRecord(node) {
    return (
        node?.type === "MemberExpression" &&
        !node.computed &&
        node.property?.name === "record" &&
        isPropsObject(node.object)
    );
}

/**
 * `this.props.X` / `props.X` for any X — the widget's own props, whatever key.
 *
 * Used to recognise `data[this.props.colorField]`: a read of another field whose
 * NAME arrives as an option. It is a sibling read in every sense that matters
 * here, and the field it names is not knowable statically, which is exactly why
 * such a widget cannot take a handle to its own field and be done.
 */
function isPropsMember(node) {
    return (
        node?.type === "MemberExpression" &&
        !node.computed &&
        node.property?.type === "Identifier" &&
        isPropsObject(node.object)
    );
}

/** `this.props.name` or `props.name` — the widget's own field name. */
function isPropsName(node) {
    return (
        node?.type === "MemberExpression" &&
        !node.computed &&
        node.property?.name === "name" &&
        isPropsObject(node.object)
    );
}

/**
 * Members destructured straight off the record: `const { model } = this.props.record`.
 *
 * A third under-count, found while converting `ace_field`. The member scan below
 * only sees `MemberExpression`s, so a destructure reached the record without
 * registering as a reach at all — 24 files fork-wide do it, and one of them
 * (`enterprise/mrp_workorder`) takes `_parentRecord`, a **private**. Missing
 * those made the declared surface look complete when it was not.
 */
function destructuredMembers(ast, isRecord) {
    const names = new Set();
    walk(ast, (node) => {
        if (node.type !== "VariableDeclarator" || node.id.type !== "ObjectPattern") {
            return;
        }
        if (!isRecord(node.init)) {
            return;
        }
        for (const prop of node.id.properties) {
            if (prop.type === "Property" && !prop.computed) {
                const name = prop.key?.name ?? prop.key?.value;
                if (typeof name === "string") {
                    names.add(name);
                }
            }
        }
    });
    return names;
}

/** Local identifiers that provably alias `props.record`. */
function recordAliases(ast) {
    const aliases = new Set();
    walk(ast, (node) => {
        if (node.type !== "VariableDeclarator" || !node.init) {
            return;
        }
        if (isPropsRecord(node.init) && node.id.type === "Identifier") {
            aliases.add(node.id.name);
            return;
        }
        // const { record } = this.props   /   const { record } = props
        const fromProps =
            (node.init.type === "MemberExpression" &&
                !node.init.computed &&
                node.init.property?.name === "props") ||
            (node.init.type === "Identifier" && node.init.name === "props");
        if (fromProps && node.id.type === "ObjectPattern") {
            for (const prop of node.id.properties) {
                if (prop.type === "Property" && prop.key?.name === "record") {
                    aliases.add(prop.value?.name ?? "record");
                }
            }
        }
    });
    return aliases;
}

function analyse(source) {
    const ast = espree.parse(source, PARSE);
    const aliases = recordAliases(ast);
    const isRecord = (node) =>
        isPropsRecord(node) || (node?.type === "Identifier" && aliases.has(node.name));

    const members = destructuredMembers(ast, isRecord);
    const siblings = new Set();
    const propSiblings = new Set();
    let ownValue = 0;
    let dynamic = 0;
    let unresolved = 0;
    let isWidget = false;

    walk(ast, (node) => {
        if (node.type === "Identifier" && node.name === "standardFieldProps") {
            isWidget = true;
        }
        if (node.type !== "MemberExpression") {
            return;
        }
        // <record>.MEMBER
        if (!node.computed && isRecord(node.object) && node.property?.name) {
            members.add(node.property.name);
        }
        // A read on a bare `record` this pass could not tie to props.
        if (
            !node.computed &&
            node.object?.type === "Identifier" &&
            node.object.name === "record" &&
            !aliases.has("record")
        ) {
            unresolved += 1;
        }
        // <record>.data.X  /  <record>.data[X]
        const base = node.object;
        const isRecordData =
            base?.type === "MemberExpression" &&
            !base.computed &&
            base.property?.name === "data" &&
            isRecord(base.object);
        if (!isRecordData) {
            return;
        }
        if (!node.computed) {
            siblings.add(node.property.name);
            return;
        }
        const key = node.property;
        if (
            isPropsName(key) ||
            (key.type === "Identifier" && /^(name|fieldName)$/.test(key.name))
        ) {
            ownValue += 1;
        } else if (key.type === "Literal" && typeof key.value === "string") {
            siblings.add(key.value);
        } else if (isPropsMember(key)) {
            // `data[this.props.colorField]` — ANOTHER field, named by an option
            // rather than written out. Counting these as merely `dynamic` made
            // `monetary`, `gauge` and `stat_info` look convertible when a handle
            // to the widget's own field can never reach the field they want.
            propSiblings.add(key.property.name);
        } else {
            dynamic += 1;
        }
    });

    return {
        isWidget,
        members: [...members].sort(),
        siblings: [...siblings].sort(),
        propSiblings: [...propSiblings].sort(),
        ownValue,
        dynamic,
        unresolved,
    };
}

for (const file of process.argv.slice(2)) {
    let result;
    try {
        result = analyse(readFileSync(file, "utf8"));
    } catch (error) {
        process.stderr.write(`parse failed: ${file}: ${error.message}\n`);
        process.exitCode = 1;
        continue;
    }
    process.stdout.write(`${JSON.stringify({ file, ...result })}\n`);
}
