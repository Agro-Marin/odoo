# Odoo 19.0 Core Fork

> **Purpose**: Fork aimed at improving Odoo's code quality and adding enhancements.
> **Parent**: See `$HOME/Odoo/CLAUDE.md` for environment setup, commands, and directory rules.

---

## Fork Enhancement: Playwright PDF Engine

This fork adds Playwright as an alternative PDF rendering engine alongside wkhtmltopdf.

### Benefits over wkhtmltopdf
- Modern CSS support (flexbox, grid, CSS variables)
- Better rendering consistency
- Active maintenance

### Configuration

**System-wide default** (`ir.config_parameter`):
```sql
UPDATE ir_config_parameter SET value = 'playwright' WHERE key = 'report.pdf_engine';
```

**Per-report override** (`ir.actions.report.pdf_engine` field):
| Value | Behavior |
|-------|----------|
| Empty | Use system default |
| `wkhtmltopdf` | Force wkhtmltopdf (legacy) |
| `playwright` | Force Playwright (modern) |

### Installation

```bash
pip install playwright>=1.40.0
playwright install chromium
```

### API

```python
# Check engine state
state = self.env['ir.actions.report'].get_pdf_engine_state('playwright')

# Get engine for a report
engine = report._get_pdf_engine_name()  # 'wkhtmltopdf' or 'playwright'

# Engines registry
from odoo.tools.pdf import PDF_ENGINES, get_pdf_engine
available = {name: cls for name, cls in PDF_ENGINES.items() if cls.is_available()}
```

### Key Files

| File | Purpose |
|------|---------|
| `odoo/tools/pdf/engines/__init__.py` | Base `PdfEngine` class + registry |
| `odoo/tools/pdf/engines/playwright_engine.py` | Playwright implementation |
| `odoo/addons/base/models/ir_actions_report.py` | Engine dispatch |

### Known Limitation

Playwright PDF does **not work in Odoo shell** due to Chromium sandbox conflicts. Use normal server mode.

---

## Odoo 19.0 Quick Reference

> **Full Reference**: `knowledge/agromarin-knowledge/wiki/odoo-19/odoo-19-development-context.md`

| Pattern | Deprecated (17/18) | Modern (19.0) |
|---------|-------------------|---------------|
| List views | `<tree>` | `<list>` |
| Visibility | `attrs="{'invisible': [...]}"` | `invisible="state == 'draft'"` |
| Chatter | `<div class="oe_chatter">` | `<chatter/>` |
| Groups | `groups_id` | `group_ids` |
| Constraints | `_sql_constraints = [...]` | `models.Constraint(...)` |
| Indexes | `_auto_init()` manual | `models.Index("(field1, field2)")` |
| Display name | `name_get()` | `_compute_display_name()` |
| Hooks | `hook(cr, registry)` | `hook(env)` |
| Cursor/UID | `self._cr`, `self._uid` | `self.env.cr`, `self.env.uid` |

### Declarative Indexes (Preferred in Fork)

```python
class MyModel(models.Model):
    _name = 'my.model'

    # Composite index - string with SQL expression
    _state_owner_idx = models.Index("(state, request_owner_id)")

    # Unique constraint (simple)
    _code_uniq = models.Constraint('unique(code)', 'Code must be unique!')

    # Partial unique index (with WHERE clause)
    _event_uniq = models.UniqueIndex(
        '(state_id, event_id) WHERE event_id IS NOT NULL',
        'Event ID must be unique per state!'
    )
```

---

## XPath Rules

**MANDATORY**: Read parent view file before writing XPath. Never guess structure.

```xml
<!-- ✅ Specific locators -->
<xpath expr="//field[@name='partner_id']" position="after">
    <field name="custom_field"/>
</xpath>

<!-- ❌ Avoid generic paths (break easily) -->
<xpath expr="//sheet/group" position="after">
```

---

## Development Standards

- **English only**: All code, comments, docstrings
- **Mandatory docstrings**: Every method and class
- **PEP 8 compliance**, meaningful names, type hints
- **Commit format**: `[TAG] module: description` (IMP, FIX, ADD, REF)

---

## Git Workflow

### Branch Naming Convention

Use the following format for all feature branches:

```
19.0-t<TASK_ID>-<username>
```

**Examples:**
- `19.0-t14367-jsuniaga` - Fix for task 14367
- `19.0-t15000-dev` - Feature for task 15000

### Workflow

1. Create feature branch from `19.0-marin`: `git checkout -b 19.0-t<TASK_ID>-<username>`
2. Make changes and commit with OCA format: `[TAG] module: description`
3. Push and create PR against `19.0-marin`

### Commit Tags

| Tag | Use |
|-----|-----|
| `[FIX]` | Bug fixes |
| `[IMP]` | Improvements to existing features |
| `[ADD]` | New features |
| `[REF]` | Refactoring (no functional change) |
| `[REM]` | Removing code or features |

---

## References

- [Odoo 19.0 Developer Docs](https://www.odoo.com/documentation/19.0/developer.html)
- Full Odoo 19 migration guide: `knowledge/agromarin-knowledge/wiki/odoo-19/odoo-19-development-context.md`
