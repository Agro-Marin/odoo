# Native ESM Conversion — Task Prompt

**Copy this entire file as a prompt for a new Claude Code context window.**

---

## Task

Convert all JavaScript files in `core/addons/web/static/src/` from legacy transpiled modules (`@odoo-module`) to browser-native ES modules (`@odoo-module native`). This is a mechanical transformation — no logic changes, no refactoring.

## Background

The Odoo JS module system currently uses a Python regex transpiler that transforms ES6 `import`/`export` into `odoo.define()` wrapper calls. We're migrating to browser-native ESM with import maps. The full infrastructure is already committed and working with 18 pilot modules.

**How it works:**
- Files with `@odoo-module native` skip Python transpilation entirely
- They're excluded from the concatenated bundle and served individually
- An import map in the HTML resolves bare specifiers (`@web/core/registry` → `/web/static/src/core/registry.js`)
- A bridge `<script type="module">` registers native modules in `odoo.loader` so legacy `require()` still works
- The module_loader.js `registerNativeModules()` propagates dependencies

## What to change per file

Each file needs exactly TWO transformations:

### 1. Change the module header

```javascript
// BEFORE (any of these variants):
/** @odoo-module */
/** @odoo-module **/

// AFTER:
/** @odoo-module native */
```

### 2. Add `.js` extension to ALL relative imports

Browser-native ESM resolves relative imports as URLs. Without `.js`, the server returns 404.
The import map only handles bare specifiers (`@web/...`, `@odoo/owl`), NOT relative paths.

```javascript
// BEFORE:
import { Foo } from "./foo";
import { Bar } from "../bar";
import { Baz } from "./subdir/baz";

// AFTER:
import { Foo } from "./foo.js";
import { Bar } from "../bar.js";
import { Baz } from "./subdir/baz.js";
```

**Bare specifiers do NOT need `.js`** — the import map handles them:
```javascript
// These are CORRECT as-is, do NOT add .js:
import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
```

## Files to SKIP (do NOT convert)

- `module_loader.js` — has `@odoo-module ignore`, bootstraps the module system itself
- `service_worker.js` — has `@odoo-module ignore`, runs in service worker context
- Any file already marked `@odoo-module native` (18 files in `core/utils/`)
- `legacy/js/public/public_root.js` — has `@odoo-module alias=root.widget`

## Conversion statistics

| Item | Count |
|------|-------|
| Total JS files in `web/static/src/` | 608 |
| Already native | 18 |
| To skip (ignore/alias) | 3 |
| Files to convert | ~587 |
| Files with relative imports needing `.js` | ~154 |
| Total relative import occurrences | ~230 |

## Implementation approach

Write a Python script that:

1. Walks `core/addons/web/static/src/` recursively
2. For each `.js` file:
   a. Reads the content
   b. Skips if already `native`, `ignore`, or has `alias=`
   c. Replaces `/** @odoo-module */` → `/** @odoo-module native */`
   d. Replaces `/** @odoo-module **/` → `/** @odoo-module native */`
   e. Finds all relative imports and adds `.js` extension:
      - Pattern: `from ["'](\.\.?/[^"']+)["']` where the path doesn't already end in `.js`
      - Also handle: `import ["'](\.\.?/[^"']+)["']` (side-effect imports)
   f. Writes the file back

The regex for relative imports:
```python
import re

def add_js_extension(content):
    """Add .js to relative import paths that don't already have it."""
    def fix_import(m):
        prefix = m.group(1)  # 'from "' or "from '" or 'import "'
        path = m.group(2)     # the relative path
        quote = m.group(3)    # closing quote
        if not path.endswith('.js'):
            path += '.js'
        return f'{prefix}{path}{quote}'

    # Match: from "./path" or from '../path' or import "./path"
    # Captures: (prefix)(path)(quote)
    pattern = r'''((?:from|import)\s+['"])(\.\.?/[^'"]+)(['"])'''
    return re.sub(pattern, fix_import, content)
```

## Verification

After running the script:

1. **Count check**: `grep -rl '@odoo-module native' core/addons/web/static/src/ --include="*.js" | wc -l` should be ~605 (608 - 3 skipped)

2. **No extensionless relative imports**: `grep -rP "from ['\"]\.\.?/[^'\"]+(?<!\.js)['\"]" core/addons/web/static/src/ --include="*.js"` should return 0 results

3. **Run tests**:
   ```bash
   cd /home/marin/Odoo
   : > ./odoo.log && ./venv/odoo/bin/python ./core/odoo-bin -c ./conf/odoo.conf -d test_db \
       --test-tags '/test_assetsbundle' -u test_assetsbundle --stop-after-init --workers=0
   grep "tests when loading" ./odoo.log
   ```
   Expected: 100/102 pass (2 pre-existing browser tour failures: DuplicatedKeyError html_field, ErrorHandler not Component)

4. **Webclient smoke test**:
   ```bash
   : > ./odoo.log && ./venv/odoo/bin/python ./core/odoo-bin -c ./conf/odoo.conf -d dev_db --dev=all &
   # Wait for startup, then:
   curl -s http://localhost:8069/web/login | grep importmap
   # Should show import map with ~605 entries
   ```

## Important constraints

- **Do NOT modify any Python files** — the infrastructure is already committed and working
- **Do NOT modify `module_loader.js`** — it's the bootstrap, must stay as `@odoo-module ignore`
- **Do NOT add `.js` to bare specifiers** — `@web/...` and `@odoo/owl` are resolved by import map
- **Do NOT change any logic** — this is purely a mechanical annotation + extension change
- **Do NOT convert files in `static/tests/`** — only `static/src/`
- **Preserve `// @ts-check`** lines — many files have this before `@odoo-module`, keep it

## After web/ is done

The same process applies to other addons. Priority order:
1. `mail` (378 files, 53 with relative imports)
2. `html_editor` (187 files, 87 with relative imports)
3. `website` (348 files, 100 with relative imports)
4. `project` (119 files, 67 with relative imports)
5. `account` (72 files), `stock` (40), `sale` (37), `hr` (36), `mrp` (26), `bus` (20), `portal` (27), `web_tour` (16), `purchase` (15), `product` (15)

Each addon follows the same pattern — the import map in `ir_qweb.py` automatically picks up native modules from any addon's bundle.
