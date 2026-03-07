# Phase PC-02 — `core/` root + `core/browser/` + `core/errors/` + `core/colors/` + `core/position/` Audit Output

**Scope**: `static/src/core/` flat files + `browser/` + `errors/` + `colors/` + `position/`
**File count**: 20
**Status**: COMPLETE — 3 bugs fixed, 3 SKIPs documented

Files:
`domain.js`, `registry.js`, `assets.js`, `events.js`, `context.js`, `template_inheritance.js`,
`templates.js`, `action_hook.js`, `constants.js`,
`browser/browser.js`, `browser/cookie.js`, `browser/feature_detection.js`,
`browser/anchor_scroll.js`, `browser/hotkeys.js`, `browser/router.js`,
`errors/error_utils.js`, `errors/uncaught_errors.js`,
`colors/colors.js`, `position/position_hook.js`, `position/utils.js`

---

## Fixed Findings

---

### `errors/error_utils.js:148` — [P1] C-03 — `error.stack` accessed without null guard

**Code**:
```js
function formatTraceback(error) {
    let traceback = error.stack;       // could be undefined
    // ...
    if (error.stack.split("\n")[0].trim() !== descriptionLine) {  // crash if undefined!
        traceback = `${descriptionLine}\n${error.stack}`.replace(/\n/g, "\n    ");
    }
    return traceback;
}
```

**Problem**: `error.stack` is accessed twice — first assigned to `traceback`, then directly in the condition — without null guard. If `error.stack` is undefined (e.g. custom error subclass that clears the stack, or a non-standard thrown value propagating through), `undefined.split(...)` throws TypeError. Inconsistent with `annotateTraceback` in the same file, which correctly guards with `if (error.stack)` before accessing stack.

**Fix**:
```js
function formatTraceback(error) {
    const stack = error.stack ?? "";
    // ...
    if (stack && stack.split("\n")[0].trim() !== descriptionLine) {
        return `${descriptionLine}\n${stack}`.replace(/\n/g, "\n    ");
    }
    return stack || descriptionLine;
}
```

---

### `colors/colors.js:152` — [P1] C-03 — `hexToRGBA` crashes on non-matching hex input

**Code**:
```js
export function hexToRGBA(hex, opacity) {
    const rgb = RGB_REGEX.exec(hex)  // returns null if hex is invalid
        .slice(1, 4)                  // TypeError: Cannot read properties of null
        ...
}
```

**Problem**: `RGB_REGEX.exec(hex)` returns `null` when `hex` is not a valid 6-digit hex color (e.g. empty string, `#abc` 3-digit shorthand, CSS color names, gradient strings). Calling `.slice()` on `null` throws TypeError and crashes the entire chart/graph render that called `hexToRGBA`.

**Fix**:
```js
export function hexToRGBA(hex, opacity) {
    const match = RGB_REGEX.exec(hex);
    if (!match) {
        return `rgba(0,0,0,${opacity})`;
    }
    const rgb = match.slice(1, 4).map((n) => parseInt(n, 16)).join(",");
    return `rgba(${rgb},${opacity})`;
}
```

---

### `assets.js:75` — [P3] M-02 — `pagehide` listener accumulates, never removed

**Code**:
```js
window.addEventListener("pagehide", () => {
    removeListeners();
});
```

**Problem**: This listener is registered inside `onLoadAndError`, which is called once per CSS/JS asset load. A typical Odoo page loads 50-100+ assets, creating that many anonymous `window` pagehide listeners. Each closure holds references to `el`, `onLoadListener`, and `onErrorListener`, preventing GC until `pagehide` fires. Since `pagehide` fires exactly once per page lifetime, the fix is `{ once: true }`.

**Fix**:
```js
window.addEventListener("pagehide", () => {
    removeListeners();
}, { once: true });
```

---

## Skip Registry

---

### `browser/browser.js:62-63` — dead `innerHeight`/`innerWidth` initial values — SKIP

Lines 62-63 set `innerHeight: window.innerHeight` and `innerWidth: window.innerWidth` as snapshot values in the `browser` object literal, but `Object.defineProperty` at lines 79-86 immediately overrides them with live getters. The initial snapshot assignments are M-01 dead code. Intentional historical artifact — `Object.defineProperty` cannot be inlined in an object literal, so the static assignments served as a placeholder. Harmless.

---

### `template_inheritance.js:19` — `getTranslationContext` no base case for null parentElement — SKIP

`getTranslationContext` recurses into `el.parentElement` without guarding for null. If it reaches the root element with no TCTX attribute, the next call gets `null` as argument and crashes. In practice, `applyInheritance` always sets `translationContext` at the top level and `_getTemplate` sets the TCTX attribute on template root elements, so traversal always terminates before null. Latent fragility — not a triggered crash path in current code.

---

### `position_hook.js:61` — `options.position` mutation — SKIP

`update()` writes `options.position = \`${solution.direction}-${solution.variant}\``, mutating the caller's options object. Comment says `// memorize last position`. This is intentional sticky behavior — the hook remembers its last successful position to use as the next positioning preference. Documented design decision.

---

## Files with No Findings

`domain.js`, `registry.js`, `events.js`, `context.js`, `templates.js`, `action_hook.js`,
`constants.js`, `browser/browser.js` (skip noted), `browser/cookie.js`,
`browser/feature_detection.js`, `browser/anchor_scroll.js`, `browser/hotkeys.js`,
`browser/router.js`, `errors/uncaught_errors.js`, `position/position_hook.js` (skip noted),
`position/utils.js`
