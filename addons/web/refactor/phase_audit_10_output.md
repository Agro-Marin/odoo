# Phase 10 Audit: Smaller Components

**Scope**: `core/addons/web/static/src/components/` -- 38 files across 24 subdirectories (~6,000 lines)

## Bugs Found and Fixed

### [P1] C-01: `rpcErrorHandler` crashes on null `data` (error_handlers.js:68)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/errors/error_handlers.js`
**Bug**: `originalError.data.context` accessed without null check. `RPCError.data` defaults to `null` (see `rpc.js:55`). When an RPC error has no `exceptionName` match AND `data` is null, this line throws `TypeError: Cannot read properties of null`.
**Impact**: Error dialog fails to render for RPC errors without structured data, swallowing the original error.
**Fix**: Changed to `originalError.data?.context` (optional chaining).

### [P1] C-02: `setMode` duplicate-mode guard broken (name_and_signature.js:327)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/signature/name_and_signature.js`
**Bug**: `mode === /** @type {any} */ (this).signMode` reads `this.signMode` which is `undefined` (property lives at `this.state.signMode`). The early-return guard never fires, so every call to `setMode("auto")` clears and redraws the signature even when already in auto mode, causing visible flickering.
**Fix**: Changed to `mode === this.state.signMode`.

### [P1] C-03: `defaultProps.width` does not match prop name `initialWidth` (resizable_panel.js:200)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/resizable_panel/resizable_panel.js`
**Bug**: `defaultProps` declares `width: 400` but the actual prop name is `initialWidth`. Result: `this.props.initialWidth` is `undefined` when not explicitly passed, so `useResizable` receives `undefined` as `initialWidth` and falls back to its own default (400). The defaultProps entry is dead code that never provides its value.
**Fix**: Renamed `width` to `initialWidth` in `defaultProps`.

### [P2] C-04: `activateFile` does not reset zoom/rotation/pan state (file_viewer.js:94-97)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/file_viewer/file_viewer.js`
**Bug**: Switching between files preserves the previous file's zoom scale, rotation angle, and pan translation. If user zoomed to 3x and rotated 180deg on one image, the next image inherits those settings.
**Fix**: Reset `state.scale`, `state.angle`, `state.imageLoaded`, and `translate` in `activateFile`.

### [P2] C-05: `onClickPrint` crashes if popup blocked (file_viewer.js:249)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/file_viewer/file_viewer.js`
**Bug**: `window.open()` returns `null` when popup blocker is active. Next line `printWindow.document.open()` throws `TypeError: Cannot read properties of null`.
**Fix**: Added null guard with early return.

### [P2] C-06: `updateZoomerStyle` crashes when refs not mounted (file_viewer.js:217)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/file_viewer/file_viewer.js`
**Bug**: `this.imageRef.el.offsetWidth` accessed without checking if `.el` is non-null. Can happen if `resetZoom`/`zoomIn`/`zoomOut` are triggered via keyboard while viewing a non-image file (PDF, video) where the image ref is not mounted.
**Fix**: Added null guard at top of `updateZoomerStyle`.

### [P3] M-01: Typo "Occured" in error context (error_dialogs.js:85)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/errors/error_dialogs.js`
**Bug**: `"Occured "` should be `"Occurred "`. This string appears in error clipboard text and the error dialog UI.
**Fix**: Corrected spelling.

## Issues Found but NOT Fixed (Require Broader Changes)

### [P2] C-07: `onClickPrint` XSS via `defaultSource` injection (file_viewer.js:265)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/file_viewer/file_viewer.js`
**Issue**: `this.state.file.defaultSource` is interpolated directly into an HTML string via template literal: `<img src="${this.state.file.defaultSource}">`. If a file's URL contains `" onerror="alert(1)`, it could execute arbitrary JavaScript in the print window context. Low practical risk since `defaultSource` is computed from server-controlled data, but the pattern is unsafe.
**Recommendation**: Use `document.createElement` instead of string interpolation.

### [P2] C-08: `connectionLostNotifRemove` is module-level shared state (error_handlers.js:99)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/errors/error_handlers.js`
**Issue**: Module-level `let connectionLostNotifRemove = null` persists across environments. In test scenarios with multiple environments, a notification remove function from one env leaks to another.
**Recommendation**: Move into per-env state or use a WeakMap keyed by env.

### [P3] C-09: `ResizablePanel` template name mismatch (resizable_panel.js:184)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/resizable_panel/resizable_panel.js`
**Issue**: `static template = "web_studio.ResizablePanel"` -- a `web` module component references a `web_studio` template name. The corresponding XML file at `resizable_panel.xml` does define `t-name="web_studio.ResizablePanel"` so it works, but the naming convention is wrong. This component was likely extracted from `web_studio` but the template name was never updated to `web.ResizablePanel`.
**Impact**: Confusing developer experience; works correctly at runtime.

### [P3] C-10: `Notebook.page` getter can throw on stale currentPage (notebook.js:119)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/notebook/notebook.js`
**Issue**: `this.pages.find((e) => e[0] === this.state.currentPage)[1]` -- if `find` returns `undefined` (stale `currentPage`), accessing `[1]` throws. Guarded by `computeActivePage` logic but fragile.

### [P3] M-02: `isDisable` naming (file_input.js:53)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/file_input/file_input.js`
**Issue**: State property `isDisable` should be `isDisabled` (adjective form). Also referenced in XML template. Cosmetic but inconsistent with the rest of the codebase which uses `isDisabled`.

### [P3] M-03: `FileUploadProgressRecord` base class has empty template string (file_upload_progress_record.js:10)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/file_upload/file_upload_progress_record.js`
**Issue**: `static template = ""` -- the base class has an empty template. It relies entirely on subclasses (`FileUploadProgressKanbanRecord`, `FileUploadProgressDataRow`) to set proper templates. If the base class is ever instantiated directly, it renders nothing.

### [P3] P-01: CodeEditor `useEffect` re-creates Ace on every `value`/`sessionId` change (code_editor.js:156)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/code_editor/code_editor.js`
**Issue**: The effect at line 156 depends on `[sessionId, mode, value]`. Every `value` change (e.g., each keystroke in a parent-controlled editor) triggers the effect, which calls `session.setValue()` even though the value might already match (the `getValue() !== value` guard helps but the effect still fires). For large files with frequent updates, this is suboptimal.

### [P3] P-02: `Dropzone.setup` calls `super.setup()` unnecessarily (dropzone.js:17)
**File**: `/home/marin/Odoo/core/addons/web/static/src/components/dropzone/dropzone.js`
**Issue**: `super.setup()` is called but `Component.setup()` is a no-op. Harmless but unnecessary.

## Summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| [P1] Production bugs | 3 | 3 | 0 |
| [P2] Edge case bugs | 3 | 3 | 2 |
| [P3] Code quality | 1 | 1 | 6 |
| **Total** | **7** | **7** | **8** |

### Files Modified
1. `/home/marin/Odoo/core/addons/web/static/src/components/errors/error_handlers.js` -- null safety on `data.context`
2. `/home/marin/Odoo/core/addons/web/static/src/components/errors/error_dialogs.js` -- "Occurred" typo
3. `/home/marin/Odoo/core/addons/web/static/src/components/signature/name_and_signature.js` -- `setMode` guard fix
4. `/home/marin/Odoo/core/addons/web/static/src/components/resizable_panel/resizable_panel.js` -- defaultProps key fix
5. `/home/marin/Odoo/core/addons/web/static/src/components/file_viewer/file_viewer.js` -- zoom reset, popup guard, ref guard
