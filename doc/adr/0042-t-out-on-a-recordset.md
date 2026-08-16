# ADR-0042: What `t-out` should render when the value is a recordset

- **Status:** Proposed
- **Date:** 2026-08-16

## Context

QWeb's `t-out` emits its value through `_compile_out_emit`, whose generated code
ends in:

```python
yield str(escape(content))
```

A recordset has no `__html__`, so `escape` falls through to `str()` and the
template renders Python's debugging repr:

```
<t t-out="object.partner_id"/>   ->   res.partner(3,)
```

`t-field` does not have this problem — it routes through `_get_field` and the
field's own formatter — and neither does `t-out` with `t-options={'widget': …}`,
which routes through `_get_widget`. Only the bare form falls through.

This surfaced from the other side. `mail.render.mixin` has two renderers behind
`engine="qweb"`: the real `ir.qweb`, and an evaluation-free one that resolves a
dotted path itself for non-editors (`d475a875f49`). The stock allow-list
`mail_allowed_qweb_expressions()` ships `object.partner_id` and `object.user_id`,
so a relational placeholder is *expected* input. The evaluation-free renderer
answers `Ben & Jerry`; `ir.qweb` answers `res.partner(3,)`. `1dc54a48438` closed
five of the six divergences between those two renderers and could not close this
one, because it is not a mail question — it is what `t-out` means.

### How far the current behaviour reaches, measured

Two independent measurements, because the first one nearly produced a false
negative: an instrument placed on `_compile_to_str` logged nothing, and the
reason was that the bare `t-out` path does not call it. Verify the instrument
fires before trusting a zero.

**Static, per element** (`t-out` / `t-esc` / `t-raw` whose expression is a bare
dotted path ending in `_id`/`_ids`, excluding `position=` inheritance locators
and `static/` client templates):

| Tree | XML files | Candidates | With `t-options` | Bare |
|---|---|---|---|---|
| `odoo/addons` | 3515 | 25 | 16 | 9 |
| `odoo/odoo/addons` | 90 | 1 | 0 | 1 |
| `enterprise` | 3736 | 38 | 1 | 37 |
| `agromarin` | 938 | 0 | 0 | 0 |
| `design-themes` | 1152 | 0 | 0 | 0 |

Every one of the ten bare hits in the community trees was read and is a false
positive: `line_id` is `<t t-set="line_id" t-value="1"/>` — an integer counter;
`pos_order_id` renders as *"Order ID: 42"*; `document_context_id`,
`ubl_version_id` and `customization_id` are EDI schema constants; `country_id`
is inside `ir_qweb_widget_templates.xml`, which is the widget machinery itself.
So **no shipped community template renders a bare recordset**, and neither
sibling repo has a candidate at all.

**Runtime**, wrapping the `escape` that `_prepare_globals` hands to generated
code, over the install *and* full test run of `mail, test_mail, mass_mailing,
portal, website, account, sale_management, stock`: **two events, both from
`test_mail_hardening_v19.py:52`** — the characterisation test written to record
this very divergence. Zero from product code.

### The enterprise residual, cleared

The 37 were resolved individually — not by name, which cannot decide them, but by
following each expression to what binds it. Every one is a scalar; **none is a
recordset.**

| Shape | Sites | What they resolve to |
|---|---|---|
| `root.field` on a record | 11 | `fields.Char` throughout — `hr.version.passport_id`, `hr.version.identification_id`, `account.281.50.form.official_id`, `l10n_ch.location.unit.in_house_id`, `res.company.income_tax_id`, `res.company.l10n_mx_imss_id` — or a plain attribute on a Python helper (`hr_dmfa`'s `worker`/`contribution` objects, where `local_unit_id` is assigned `-1` or a `format_amount()` string) |
| bare, bound by `t-set` | 2 | `saft_report`'s `partner_id` is `invoice_vals['partner_id']`, used one line later as `partner_detail_map[partner_id]` — a dict key, an int |
| bare, from the render context | 24 | `uuid4()` (`l10n_dk` ×3), `findtext()` on an lxml tree (`l10n_co_dian` ×2), `ir.sequence.next_by_id()` (`l10n_cl_edi` ×3), a `<int:shift_id>` route parameter (`planning`), `company.vat` (`l10n_ma`), `format_amount(...)` (`l10n_be_hr_payroll`), and `fields.Char` reads — `dian_testing_id`, `dian_software_id`, `l10n_fr_intrastat_envelope_id`, `zip_key`, `identifier`, `serial` |

**What this method cannot see, and what would.** The scan that produced the
candidates keyed on the `_id`/`_ids` naming convention, so a recordset reaching
`t-out` under any other name is outside it — a `t-set` variable called `partner`,
or a relational field not following the convention. Only the runtime instrument
covers that, and over the community modules it found nothing. The same run
against the enterprise l10n set **did not complete**: it aborted during install
on `l10n_sk_reports`, whose `annual_statements_menuitem.xml` references
`account_reports.action_account_report_asr`, an action that does not resolve in
this workspace. That is an environment fault unrelated to this decision, but it
means the enterprise trees have per-site clearance and no runtime sweep.

## Decision

**Proposed:** `t-out` renders a recordset as its display name — `display_name`
for a single record, the display names joined for several, and the empty string
for an empty recordset — instead of `str(recordset)`.

The change belongs in `_compile_out_emit`'s emit step, the one place the bare
path passes through, so `t-field` and widget rendering are untouched.

## Alternatives considered

**Leave it, and let `t-field` be the answer.** Defensible — a template author who
writes `t-out` on a relation arguably meant `t-field` — but it makes the
framework's response to a common mistake a Python repr in a customer-facing
document, and it leaves `mail`'s two renderers permanently disagreeing on input
its own allow-list advertises.

**Fix it in `mail` only.** There is nowhere to put it: mail cannot intercept
attribute access on `object`, and its `ir.qweb` subclass is `_inherit`, so any
change there is registry-wide anyway — the same blast radius with less of the
benefit.

**Route the bare path through `_compile_to_str`.** That helper already maps
`None`/`False` to `""` and is used by `t-field`, widgets and text nodes, so it
looks like the natural home. It is not: it returns `str`, and the bare path must
preserve `Markup` for html fields. Adding the recordset case to it would fix
`t-field`'s fallback and text interpolation as a side effect, which is a wider
decision than this one.

## Consequences

**Where it fires, it can only improve the output.** There is no template for
which `res.partner(3,)` is the intended text, so any site whose rendering
changes is a site currently emitting a Python repr into a document. The risk is
therefore not *wrong output* — it is **tests that pin the repr**, and enterprise
EDI snapshots are where those would live.

**An empty recordset changes category.** Today it renders `res.partner()`; under
this decision it renders empty. If it is normalised to `False` rather than `""`
it would additionally start using `t-out`'s default body, which is a second,
larger behaviour change — this ADR proposes the empty string, not the fallback.

**Reading becomes possible where it was not.** `display_name` is a field read, so
a recordset the user cannot read would raise `AccessError` where it previously
printed ids. That is the correct direction — printing ids of unreadable records
is a leak — but it is a new failure mode on a path that previously could not
fail.

**It does not close the mail divergence on its own.** It closes it for
`object.partner_id` and `object.user_id`, which is what the stock allow-list
ships. A model that allow-lists a relational path whose display name differs
from what the evaluation-free renderer computes would still diverge; the
differential suite (`test_mail_hardening_v19`) is what keeps that visible.

## What `Accepted` would require

1. ~~The enterprise l10n set installed under the runtime instrument, and the 37
   candidates cleared or listed.~~ **Done for the candidates** (all 37 resolved,
   above); the runtime sweep over enterprise is still owed, and needs
   `l10n_sk_reports` installable first.
2. The implementation in `_compile_out_emit`, with the multi-record and empty
   cases covered.
3. A before/after failure-set comparison across community and enterprise, in the
   two-worktree shape used for `1dc54a48438`.
