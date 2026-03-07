# Phase PC-04 — `core/tree/` + `model/` root Audit Output

**Scope**: `static/src/core/tree/` (16 files) + `static/src/model/` root (6 files)
**File count**: 22
**Status**: COMPLETE — 4 bugs fixed, 0 SKIPs

Files — `core/tree/`:
`ast_utils.js`, `condition_tree.js`, `construct_domain_from_tree.js`,
`construct_expression_from_tree.js`, `construct_tree_from_domain.js`,
`construct_tree_from_expression.js`, `domain_contains_expressions.js`,
`domain_from_tree.js`, `expression_from_tree.js`, `in_range_options.js`,
`operator_labels.js`, `operators.js`, `tree_from_domain.js`,
`tree_from_expression.js`, `utils.js`, `virtual_operators.js`

Files — `model/`:
`model.js`, `record.js`, `sample_data.js`, `sample_field_generators.js`,
`sample_server.js`, `types.js`

---

## Fixed Findings

---

### `core/tree/condition_tree.js:267-274` — [P3] M-01 — dead `if` branch in `normalizeConnector`

**Code**:
```js
if (newTree.negate) {
    const newChild = { ...child, negate: !child.negate };
    if (newChild.type === "condition") {
        return newChild;   // both branches return newChild
    }
    return newChild;       // dead — same result regardless of type
}
```

**Problem**: The condition `if (newChild.type === "condition")` is dead code — both the `if` branch and the implicit `else` return `newChild` unchanged. Originally the connector case likely had different logic, which was removed, leaving the type-check meaningless.

**Fix**:
```js
if (newTree.negate) {
    return { ...child, negate: !child.negate };
}
```

---

### `core/tree/virtual_operators.js:284-288` — [P1] C-03 — `bounds.find()` null dereference on unknown `valueType`

**Code**:
```js
const bounds = getBounds(generateSmartDates, fieldType);
const [, leftBound, rightBound] = bounds.find(([v]) => v === valueType);  // crashes if valueType not found
```

**Problem**: `Array.find()` returns `undefined` when no entry matches. Destructuring `undefined` throws `TypeError: undefined is not iterable`. This triggers when a domain tree contains an `"in range"` condition whose `valueType` is not in the predefined `BOUNDS_*` arrays — e.g. a future period name, a manually constructed tree, or deserialization of a domain from a newer server version. The function is called by `eliminateVirtualOperators` → `domainFromTree`, crashing the entire domain-to-string conversion.

**Fix**:
```js
const bounds = getBounds(generateSmartDates, fieldType);
const found = bounds.find(([v]) => v === valueType);
if (!found) {
    return; // unknown valueType — leave condition untouched
}
const [, leftBound, rightBound] = found;
```

---

### `model/record.js:145-158` — [P1] C-04 — stale closure loses many2one ID when display name is fetched

**Code**:
```js
} else if (Array.isArray(values[fieldName])) {
    if (values[fieldName][1] === undefined) {
        const prom = loadDisplayName(values[fieldName][0]);
        prom.then((displayName) => {
            values[fieldName] = {
                id: values[fieldName][0],   // BUG: reads from already-mutated object
                display_name: displayName,
            };
        });
        proms.push(prom);
    }
    values[fieldName] = {               // synchronous mutation: array → object
        id: values[fieldName][0],
        display_name: values[fieldName][1],  // undefined
    };
```

**Problem**: When a many2one value arrives as `[id, undefined]` (ID provided but display name missing), the code synchronously overwrites `values[fieldName]` with an object `{ id, display_name: undefined }` *after* registering the `.then()` callback. When the callback fires, `values[fieldName]` is now an object, so `values[fieldName][0]` returns `undefined` (numeric index on a plain object). The record field is set to `{ id: undefined, display_name: "Real Name" }` — the record ID is silently lost, breaking relational lookups, form saves, and field navigation.

**Fix** (capture ID before synchronous mutation):
```js
} else if (Array.isArray(values[fieldName])) {
    if (values[fieldName][1] === undefined) {
        const originalId = values[fieldName][0];
        const prom = loadDisplayName(originalId);
        prom.then((displayName) => {
            values[fieldName] = {
                id: originalId,
                display_name: displayName,
            };
        });
        proms.push(prom);
    }
    values[fieldName] = {
        id: values[fieldName][0],
        display_name: values[fieldName][1],
    };
```

---

### `model/sample_server.js:406` — [P3] M-03 — typo "Invalidate" in error message

**Code**:
```js
throw new Error(`Invalidate Aggregate "${measureSpec}" in SampleServer`);
```

**Problem**: "Invalidate" is a verb meaning "to make invalid" — the intended word is the adjective "Invalid". Makes the error message hard to read and hard to `grep` for.

**Fix**:
```js
throw new Error(`Invalid Aggregate "${measureSpec}" in SampleServer`);
```

---

## Files with No Findings

`core/tree/`: `ast_utils.js`, `construct_domain_from_tree.js`, `construct_expression_from_tree.js`,
`construct_tree_from_domain.js`, `construct_tree_from_expression.js`, `domain_contains_expressions.js`,
`domain_from_tree.js`, `expression_from_tree.js`, `in_range_options.js`, `operator_labels.js`,
`operators.js`, `tree_from_domain.js`, `tree_from_expression.js`, `utils.js`

`model/`: `model.js`, `sample_data.js`, `sample_field_generators.js`, `types.js`
