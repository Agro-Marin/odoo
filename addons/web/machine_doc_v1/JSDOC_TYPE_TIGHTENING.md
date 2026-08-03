# JSDoc Type Tightening — Migration Recipe

> Recipe for eliminating `/** @type {any} */` escape hatches in seam files
> WITHOUT migrating to actual `.ts` files. The asset pipeline (the `assetsbundle/`
> package's URL stripping, `ir_qweb_assets.py` URL extension forcing) hardcodes `.js` in 6+
> sites; flipping a file's extension would require a separate infrastructure
> change.

## When to apply

Apply to files that already carry `// @ts-check` and have multiple
`/** @type {any} */` escapes; highest-value targets are the model/network
seam. Skip files where `any` is genuinely warranted (dynamic registry
values, framework-level proxy types that escape JSDoc's expressiveness).

## Type-check setup

The core repo ships a committed root `tsconfig.json` (`noEmit: true`,
`allowJs: true`, `types: []`); CI type-checks against it (see "CI gating").
The `@types/` ambients are loaded as ordinary program files by the `include`
glob — `**/*.ts` matches `.d.ts` — not as `@types` packages, which is why
`typeRoots` is absent: it resolves `<root>/<pkg>/index.d.ts`, and nothing in
those folders provides one. Opt-in editor template at
`addons/web/tooling/_jsconfig.json`; `addons/web/tooling/enable.sh` copies it to
an untracked repo-root `jsconfig.json`. The template is the committed artefact —
edit it, not the generated copy, which `enable.sh` overwrites.

Check a single file against the full program rather than in isolation — run the
real config and filter to the file. An isolated program under-resolves the
framework ambients and invents errors:

```bash
npx tsc -p tsconfig.strict.json --noEmit 2>&1 | grep -F "<path>("
```

## The 8 recurring tightening patterns

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

The string `"list.text"` is fragile: a typo registers an unreachable key.
The lookup-time prefix walk (`getFieldFromRegistry` → `[jsClass, viewType, ""]`)
silently falls back to the default widget, so the noise is invisible until
you grep the bundle for orphan keys.

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

**Don't drop the string form** — 79 of the 110 fork-wide `registerField` /
`registerFallbackField` sites are plain strings with no view prefix and no typo
risk; the other 31 already use the spec object. Reserve the typed form for
view-prefixed registrations and for `aliases`, which the string form cannot
express.

**Naming nuance**: the `name` in `FieldRegistrationSpec.name` is the widget
identifier the view arch references via `widget="<name>"`, NOT necessarily a
field type — `res_partner_many2one` is a widget name, not a type.

### Pattern 8 — Property assigned in `setup()`, not in a constructor

The dominant shape in this codebase, and the one that will surface on almost
every model/component file you clear off a typecheck exception list.

**Symptom** — `TS2532` / `TS18048` "possibly undefined" on a property that is
unconditionally assigned:

```js
setup() {
    this.nextActionsAfterMouseup = [];   // can never be undefined at runtime
}
// …later…
this.nextActionsAfterMouseup.push(fn);   // TS2532: Object is possibly 'undefined'
```

TypeScript's definite-assignment analysis credits **only the constructor**. A
property assigned in `setup()` is inferred as `T | undefined` under
`strictNullChecks` (which `tsconfig.strict.json` enables even though the
committed `tsconfig.json` does not).

**Fix — declare a class field, but ONLY on an OWL `Component`:**

```js
export class ListController extends MultiRecordController {
    /** @type {(() => void)[]} */
    nextActionsAfterMouseup;

    setup() {
        this.nextActionsAfterMouseup = [];
    }
}
```

**The ordering rule that decides whether this is safe.** A field initialiser
runs immediately after `super()` returns, so it clobbers anything the base
constructor already assigned:

| base class | when `setup()` runs | class field safe? |
|---|---|---|
| OWL `Component` | AFTER construction — `owl.es.js` does `new C(...)` then `component.setup()` | **yes** |
| `Model` (`model/model.js`) | INSIDE its own constructor (`this.setup(params, services)`) | **no — would overwrite with `undefined`** |

Prefer deriving the type over restating it, so it cannot drift:

```js
/** @type {ReturnType<typeof import("@web/core/name_service").nameService.start>} */
nameService;
```

**When the class field is not usable** (a `Model` subclass, or a cross-file
read like `record.model.urgentSave`), use `@ts-ignore` with a comment stating
why — **not `@ts-expect-error`**. `tsconfig.strict.json` runs
`strictNullChecks: true` but the committed `tsconfig.json` — the config the
count ratchet runs — does not, so under that gate the error does not occur and
`@ts-expect-error` reports `TS2578 Unused directive`. Note the editor config
(`addons/web/tooling/_jsconfig.json`, deployed as `jsconfig.json`) *does* set `strictNullChecks: true`,
so the directive resolves differently there; `@ts-ignore` is the form that is
inert under all three.

**What does NOT work: module augmentation.** `declare module "…" { interface X { … } }`
can only **ADD** members to a class declared in a `.js` file; it cannot re-type
a member the JS file already infers. Since a `setup()`-assigned property *does*
exist on the inferred type (as `T | undefined`), augmenting it is a silent
no-op. Where it appears to work, the module is being ambiently *shadowed* by a
`.d.ts`, so the entry is an add onto the shadow rather than an override of the
real class.

**Ambient vs augmentation.** `declare module "X"` means two different things:

- in a **non-module** `.d.ts` (no top-level `import`/`export`) it is an
  **ambient declaration that REPLACES** the real module — anything it omits
  becomes invisible to importers;
- in a **module** `.d.ts` (has a top-level `import`/`export`, e.g. `export {}`)
  it is a **module augmentation**, which is purely additive.

The failure mode of the former is silent in both directions: anything the
ambient block omits reports as "no exported member" at every import site even
though the source exports it, while the block's looser `any`-heavy signatures
mask real errors in files that consume it.

`@types/` holds only what its `static/src/@types/readme.md` scopes it to — ambient declarations
for iife/global libs (`odoo`, owl, hoot, qunit, libs, registries, services,
models) plus the one legitimate augmentation, `concurrency.d.ts`. No block there
shadows a real `.js` source. **Only ever augment; never shadow.**

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
   from typedef-only changes (importing a value instead of a type).
3. **TypeScript compile**: `tsc --noEmit` — the actual win; counts new errors.

## What this recipe does NOT cover

- **Migrating to literal `.ts` files** — blocked by the `assetsbundle/`
  package hardcoding `.js` extension in URL stripping and forced-suffix logic.
  Would need 6+ pipeline patches across the `assetsbundle/` package and
  `ir_qweb_assets.py` plus a `--loader=ts:` esbuild flag.
- **CI gating** — `.github/workflows/typecheck.yml` runs three blocking gates
  (no `continue-on-error`) on every PR touching JS/TS and on every push to
  `19.0-marin` / `19.0`:

  1. **Project-wide count ratchet** — `tsc -p tsconfig.json --noEmit`, floor in
     `tooling/ratchet/baselines/tsc.json`. Read the value there, not from this
     page. The floor is not guaranteed monotonic downward: it may be corrected
     **upward** to absorb accumulated debt. It
     fails on *improvement* too — a count below the floor exits 1 to force a
     lock-in, so a fix wave that is not committed back leaves mainline red. To
     move it: `python tooling/ratchet/ratchet.py tsc --count "$N" --update`.
     See `tooling/ratchet/README.md`.
  2. **`strictNullChecks` per-file lock** over `addons/web/static/{src,tests}`.
  3. **`noImplicitAny` per-file lock** over the same scope — this is what makes
     (2) mean anything, since `any` is null-safe by fiat.

  Gates 2 and 3 are **default-deny**: a file must be clean unless it is named in
  `tooling/typecheck/exceptions/<gate>.txt`, so a file you clean must be dropped
  from that list in the same commit, and a NEW file is gated from its first
  commit. Cleaning a file therefore has a mechanical finish line. To find the
  cheapest next target:

  ```bash
  npx tsc -p tsconfig.strict.json --noEmit > /tmp/strict.log 2>&1 || true
  python tooling/typecheck/scope_gate.py strict --log /tmp/strict.log --report
  ```

  See `tooling/typecheck/README.md`.
- **Narrowing the `@types/registries` / `@types/models` interfaces** — they
  declare framework-wide shapes (`Services`, the registry categories) that a
  file inherits wholesale. Cutting a file's dependency on the loose members is
  out of scope here; the gates simply report what those declarations imply.
