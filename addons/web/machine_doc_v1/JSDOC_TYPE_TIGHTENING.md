# JSDoc Type Tightening — Migration Recipe

> Recipe for eliminating `/** @type {any} */` escape hatches in seam files
> WITHOUT migrating to actual `.ts` files. The asset pipeline (`assetsbundle.py`
> URL stripping, `ir_qweb.py` URL extension forcing) hardcodes `.js` in 6+
> sites; flipping a file's extension would require a separate infrastructure
> change. This recipe gets ~80% of the type-safety win at ~5% of the cost.

## When to apply

Apply to files that already carry `// @ts-check` and have multiple
`/** @type {any} */` escapes. Highest-value targets are the model/network
seam (per the original architecture audit):

| File | Pre-PR `any` escapes |
|---|---:|
| `core/network/rpc.js` | 11 (done — see commit log) |
| `model/relational_model/record.js` | 5 |
| `model/relational_model/relational_model.js` | 1 |
| `core/network/rpc_cache.js` | 1 |
| `webclient/actions/action_service.js` | 1 |

Skip files where `any` is genuinely warranted (e.g. dynamic registry
values, framework-level proxy types that escape JSDoc's expressiveness).

## Setup — local type-check

The repo has no committed `tsconfig.json`; the dev opt-in template at
`tooling/_jsconfig.json` (copied per-developer by `tooling/enable.sh`)
is the canonical config. For a one-off seam-file check without enabling
the full tooling:

```bash
cat > /tmp/tsconfig_seam.json << 'EOF'
{
    "compilerOptions": {
        "moduleResolution": "node",
        "baseUrl": "<repo-root>",
        "target": "ESNext",
        "noEmit": true,
        "allowJs": true,
        "checkJs": true,
        "strict": false,
        "strictNullChecks": true,
        "strictBindCallApply": true,
        "strictFunctionTypes": true,
        "skipLibCheck": true,
        "lib": ["ESNext", "DOM", "DOM.Iterable"],
        "types": [],
        "paths": {
            "@odoo/owl": ["addons/web/static/lib/owl/owl.js"],
            "@web/*": ["addons/web/static/src/*"]
        }
    },
    "include": [
        "<repo-root>/addons/web/static/src/core/network/rpc.js",
        "<repo-root>/addons/web/static/src/core/network/rpc_cache.js"
    ]
}
EOF

PATH="$NODE_DIR:$PATH" node_modules/typescript/bin/tsc --project /tmp/tsconfig_seam.json 2>&1 | grep "rpc\.js"
```

`"types": []` blocks the implicit `@types/models` / `@types/registries`
loading that errors out when run outside the full tooling install.

## The 6 recurring tightening patterns

### Pattern 1 — Late-bound field on an error class

**Before**:
```js
/** @type {any} */ (error).model = data.params.model;
```

**After**: declare the field in the class constructor.
```js
// in RPCError:
/**
 * Model that raised the error, attached by ``_rpcOnce`` after
 * ``makeErrorFromResponse`` constructs the instance.
 * @type {string | undefined}
 */
this.model = undefined;

// at the call site (no cast):
error.model = data.params.model;
```

Catches: typos in the field name (`error.mdoel` etc.); accidentally
storing a non-string value.

### Pattern 2 — `unknown` payload narrowed by structural shape

**Before**:
```js
error.exceptionName = /** @type {any} */ (errorData)?.name;
```

**After**: typedef the payload shape based on what consumers actually read.
```js
/**
 * @typedef {{
 *  name?: string;
 *  message?: string;
 *  context?: Record<string, unknown>;
 *  [extra: string]: unknown;
 * }} RPCErrorData
 */

// JsonRpcError.data is now typed as RPCErrorData, so:
error.exceptionName = errorData?.name ?? null;
```

Catches: misspelled fields when consumers read `error.data.foo`;
forgotten `?.` when the field is optional.

### Pattern 3 — Module-scoped imported class

**Before**:
```js
/** @type {any} */
let rpcCache;
rpc.setCache = function (/** @type {any} */ cache) {
    rpcCache = cache;
};
```

**After**: import the type and annotate.
```js
/** @import { RPCCache } from "@web/core/network/rpc_cache" */

/** @type {RPCCache | undefined} */
let rpcCache;

/**
 * @param {RPCCache} cache
 */
rpc.setCache = function (cache) {
    rpcCache = cache;
};
```

Catches: passing the wrong cache-like object; calling methods that
don't exist on `RPCCache`.

### Pattern 4 — Custom event detail

**Before**:
```js
rpcBus.addEventListener(RpcEvent.REQUEST, (event) => {
    const detail = /** @type {any} */ (event).detail;
    ...
});
```

**After**: typedef the event detail and use `CustomEvent<T>`.
```js
/**
 * @typedef {{
 *  data: { id: number; jsonrpc: "2.0"; method: "call"; params: Record<string, any> };
 *  url?: string;
 *  settings?: RpcSettings;
 *  result?: any;
 *  error?: NetworkError;
 * }} RpcEventDetail
 */

rpcBus.addEventListener(RpcEvent.REQUEST, (event) => {
    const detail = /** @type {CustomEvent<RpcEventDetail>} */ (event).detail;
    ...
});
```

Catches: missing fields on `detail.data.params`; passing the wrong
discriminator (e.g. accessing `detail.error` on a REQUEST event).

### Pattern 5 — Promise + bolt-on method (`.abort()`)

**Before**:
```js
/** @type {any} */ (promise).abort = function (rejectError = true) { ... };
return promise;
```

**After**: typedef a promise-with-bolt-on alias and use it consistently.
```js
/**
 * @template T
 * @typedef {Promise<T> & { abort: (rejectError?: boolean) => void }} RpcPromise
 */

/** @type {RpcPromise<any>} */ (promise).abort = function (rejectError = true) { ... };
return /** @type {RpcPromise<any>} */ (promise);
```

Catches: callers that read `.abort` on the return without the typedef;
attempts to monkey-patch other methods onto the promise.

### Pattern 6 — Runtime helper that TS can't narrow as a type predicate

**Before**:
```js
if (isObject(detail) && detail.model) {
    rpcCache?.invalidateByModel(detail.tables, detail.model);
}
```

`isObject` is `Object.prototype.toString.call(value) === "[object Object]"`,
a stricter "plain object" check than `typeof`. TS does NOT see it as a
type predicate, so `detail.model` errors with "Property 'model' does not
exist on type 'string | string[] | ...'".

**After**: keep `isObject` for runtime fidelity, cast inside the branch.
```js
if (isObject(detail)) {
    const objDetail = /** @type {{ tables?: string[]; model?: string }} */ (detail);
    if (objDetail.model && objDetail.tables) {
        rpcCache?.invalidateByModel(objDetail.tables, objDetail.model);
        return;
    }
}
```

Don't replace `isObject` with `typeof detail === "object" && !Array.isArray(detail)`
unless every emit site is audited — `isObject` rejects `Map`/`Set`/`Date`
and the weaker check would silently include them.

### Pattern 7 — Typed-spec overload on string-keyed registration helpers

**Before** (string-keyed registry helper):
```js
// _registry.js
export function registerField(name, widget, ...rest) {
    registry.category("fields").add(name, widget, ...rest);
    return widget;
}

// call site
registerField("list.text", listTextField);
registerField("liist.text", buggyVariant);  // silently registers garbage
```

The string `"list.text"` is fragile: a typo registers an unreachable key
that no view ever asks for. The lookup-time prefix walk
(`getFieldFromRegistry` → `[jsClass, viewType, ""]`) silently falls
back to the default widget, so the registration noise is invisible
until you grep the bundle for orphan keys.

**After**: keep the string form for backward compatibility, add a typed
spec overload that constrains the prefix to a union of known view types.

```js
// _registry.js
/** @typedef {"list" | "form" | "kanban" | "calendar" | "hierarchy" | "base_settings"} FieldViewPrefix */
/** @typedef {{ name: string; view?: FieldViewPrefix }} FieldRegistrationSpec */

export function fieldKey(spec) {
    return spec.view ? `${spec.view}.${spec.name}` : spec.name;
}

/**
 * @param {string | FieldRegistrationSpec} nameOrSpec
 * @param {T} widget
 * @returns {T}
 */
export function registerField(nameOrSpec, widget, ...rest) {
    const key = typeof nameOrSpec === "string" ? nameOrSpec : fieldKey(nameOrSpec);
    registry.category("fields").add(key, widget, ...rest);
    return widget;
}

// call site
registerField({ name: "text", view: "list" }, listTextField);
// Typo: TS2820 — Type '"liist"' is not assignable to type 'FieldViewPrefix'.
//   Did you mean '"list"'?
registerField({ name: "text", view: "liist" }, buggyVariant);
```

Catches: typos in the view slug (`liist`, `LIST`, `kabnan`); registration
of an unintended prefix because the union is grep-able and finite.

**Don't drop the string form** — 74 of the 94 fork-wide `registerField`
sites are plain (no view prefix) and have no typo risk; migrating them
yields no win. Reserve the typed form for view-prefixed registrations
(20 sites as of this PR's migration).

**Naming nuance**: the "name" in `FieldRegistrationSpec.name` is the
widget identifier the view arch references via `widget="<name>"`. It is
NOT necessarily a field type — `res_partner_many2one` is a widget name,
not a type. The original audit framing used `{type, view, variant}`
which conflated these; the actual API uses `name` for fidelity.

## Gotcha — `@template T` block scope

JSDoc `@template T` applies to **every `@typedef` in the same JSDoc
comment block**, not just the one immediately following it. Result:
five typedefs in one `/** */` block all become generic, and consumers
get `error TS2314: Generic type 'RPCErrorData' requires 1 type argument(s)`.

**Always split typedefs into separate JSDoc blocks**:

```js
/** Foo. @typedef {{...}} Foo */

/** Bar. @typedef {{...}} Bar */

/** Baz. @template T @typedef {Promise<T>} Baz */  // T only applies here
```

## Verification recipe

1. **Static parse**: `node --check <file>` — catches malformed JSDoc that
   would crash the asset bundler.
2. **esbuild graph**: `esbuild --bundle <entry>` — catches import drift
   from typedef-only changes (rare, but happens if you accidentally
   import a value instead of a type).
3. **TypeScript compile**: `tsc --noEmit --project /tmp/tsconfig_seam.json`
   — the actual win; counts new errors.
4. **Standalone behavior simulation**: replicate the file's logic in a
   plain Node script, assert each tightened code path still produces the
   pre-PR result for the canonical inputs. This is the cheap substitute
   for the full Hoot harness during local iteration.

## What this recipe does NOT cover

- **Migrating to literal `.ts` files** — blocked by `assetsbundle.py`
  hardcoding `.js` extension in URL stripping and forced-suffix logic.
  Would need 6+ pipeline patches across `assetsbundle.py` and
  `ir_qweb.py` plus a `--loader=ts:` esbuild flag.
- **CI gating** — no committed `tsconfig.json` means CI doesn't run
  `tsc --noEmit`. Adding a CI-friendly config is a separate infrastructure
  change with its own PR scope.
- **The `@types/registries` / `@types/models` ambient typeRoots** — these
  declare framework-wide interfaces but loading them implicitly errors out
  without the full tooling install. The seam-file checker bypasses them
  via `"types": []`; that costs a few "implicit any" warnings on registry
  reads but doesn't block validation.

## Pattern adoption status

| File | Status | Date | Escapes |
|---|---|---|---|
| `core/network/rpc.js` | Done | 2026-05-23 | 11 → 0 |
| `core/network/rpc_cache.js` | Done (1 escape — deepFreeze pattern 6) | 2026-05-23 | 1 → 0 |
| `model/relational_model/record.js` | Done (5 escapes; surfaced a `relatedPropertyField` typedef bug — declared as `string` but used as `{name, id?, displayName?}` at both write sites) | 2026-05-23 | 5 → 0 |
| `model/relational_model/relational_model.js` | Done (1 escape — `groupByInfo` shape) | 2026-05-23 | 1 → 0 |
| `webclient/actions/action_service.js` | Done (1 escape — `switchView` default-param pattern) | 2026-05-23 | 1 → 0 |
| `model/types.js` | Done (typedef fix for `relatedPropertyField`) | 2026-05-23 | 0 → 0 |
| `views/form/form_controller.js` | Partial (2 of 7 easy escapes — default-param pattern; remaining 5 are OWL-adapter casts that need broader type infrastructure) | 2026-05-23 | 7 → 5 |
| `components/errors/error_handlers.js` | Partial (1 of 8 easy escape — eliminated `(originalError).model` now that `RPCError.model` is in the typedef; remaining 7 are dynamic Component class + addon registry shapes) | 2026-05-23 | 8 → 7 |
| `fields/_registry.js` | Added typed-spec overload + `fieldKey()` helper + `FieldViewPrefix` union (Pattern 7). 20 view-prefixed call sites across 16 files migrated to the typed form. | 2026-05-25 | n/a — API addition |

**Cumulative**: 34 → 12 across the seam (any-escapes); plus 20 view-
prefixed string-key registrations migrated to typed specs. The
remaining 12 escapes are legitimate dynamic-adapter `any`s (registry
handlers that take varied shapes, Component classes attached at
runtime, OWL hook parameter coercion) where the cast IS the right tool.

**Pattern 7 typo-catching verified by tsc**: a synthetic test with
`view: "liist"` and `view: "FORM"` produces:
- `error TS2820: Type '"liist"' is not assignable to type 'FieldViewPrefix | undefined'. Did you mean '"list"'?`
- `error TS2820: Type '"FORM"' is not assignable to type 'FieldViewPrefix | undefined'. Did you mean '"form"'?`

## Drift caught while applying the recipe

1. **`relatedPropertyField` typedef vs reality** (`model/types.js:22, 52`):
   declared as `string` for both `Field` and `FieldInfo`, but both write
   sites in `record.js` assigned object literals (`{ name, id?,
   displayName? }`). The `/** @type {any} */ ({...})` cast on the
   assignment had been hiding it. Consumers only checked truthiness
   (`if (field.relatedPropertyField)`), so the bug was latent. **Fixed**
   the typedef to match reality.

2. **`groupByInfo` shape under-declared** (`relational_model.js:78`):
   declared as `Record<string, unknown>`, but the model destructures
   `{activeFields, fields}` from it at line 970. Tightened to
   `Record<string, { activeFields: ...; fields: ... }>`.

3. **8 pre-existing tsc errors in `rpc_cache.js`** (CryptoKey nullability,
   Deferred.resolve missing on type, tables-array-vs-null confusion): not
   introduced by this PR but **surfaced** by running tsc on the file.
   They were already there; the `// @ts-check` pragma was running but
   the file had never been part of any external tsc-noEmit check, so the
   drift never alerted. Documented here as the next-tier backlog.

## Next-tier work surfaced by this PR

Running `tsc --noEmit` on the seam files exposed a backlog beyond the
direct `@type {any}` escapes:

- `rpc_cache.js` — 8 errors (CryptoKey nullability, Deferred.resolve
  shape, tables param). Tightening these requires touching the
  IndexedDB/encryption flow.
- `form_controller.js` — 5 remaining adapter casts (useBus + render,
  onMounted + resolver, model.exportState through useState wrapper,
  ui.activeElement). Need OWL type plumbing.
- `error_handlers.js` — 7 remaining (dynamic ErrorComponent class field,
  registry.add validator schema). Need error-handler interface design.

These are appropriate follow-up PRs; the recipe applies but the type
infrastructure isn't all in place yet.
