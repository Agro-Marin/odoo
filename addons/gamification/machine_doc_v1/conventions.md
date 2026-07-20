# Gamification Conventions & Gotchas

## safe_eval Usage

Four models use `safe_eval` to evaluate user-defined domains or code:

| Model | Field | Variables Available |
|-------|-------|--------------------|
| `goal.definition` | `domain` | `user` (browse record of goal's user) |
| `goal` | `definition.domain` (count/sum) | `user` (browse record of goal's user) |
| `goal` | `definition.batch_user_expression` (batch) | `user` (browse record of goal's user) |
| `goal` | `definition.compute_code` (python mode) | `object` (goal), `env`, `date`, `datetime`, `timedelta`, `time` |
| `streak.type` | `domain` | `user`, `date_from`, `date_to` (string datetimes) |
| `achievement` | `trigger_domain` | `user` (browse record) |

**Security note:** `safe_eval` prevents arbitrary code execution but domains
can still read any model's data. Goal definitions with `computation_mode=python`
use `safe_eval(code, mode="exec")` which is more permissive — the `object`
variable gives access to the goal record and `env` to the full ORM environment.
Only admin users (`group_erp_manager`) can create goal definitions.

---

## Karma Tracking Invariants

1. **Never write `karma` directly on `res.users` from Python** — always use
   `user._add_karma(gain, source, reason)` or `_add_karma_batch()`.
   Direct `user.karma = X` triggers `write()` which calls `_add_karma_batch`
   internally, but loses the source/reason metadata.

2. **`origin_ref` selection** must include all models that pass themselves as
   `source` to `_add_karma`. Currently: `res.users`, `gamification.streak`,
   `gamification.kudos`, `gamification.achievement.unlock`.
   If a new module grants karma with a different source model, extend
   `_get_origin_selection_values()`.

3. **Consolidation:** Karma is the sum of all recorded gains, and a
   consolidated row carries the total gain of the rows it replaces, so
   consolidation cannot change anyone's karma and needs no special context.
   Do **not** reintroduce a `skip_karma_computation` flag: an early `return`
   from a compute does not defer it, it discards it, because the ORM clears the
   to-compute flag before calling the compute.

---

## Naming Conventions

| Pattern | Example | Rule |
|---------|---------|------|
| Model name | `gamification.streak.type` | Dot-separated, singular noun |
| Field for user | `user_id` | Always `user_id`, never `partner_id` |
| Computed count | `unlock_count`, `kudos_count` | `{thing}_count` |
| Aggregate stat | `team_karma`, `team_badges` | `team_{metric}` |
| Readonly computed | `readonly=True` (default) | Explicit `readonly=False` for editable |

---

## Cron Jobs

| XML ID | Model | Schedule | Method |
|--------|-------|----------|--------|
| `ir_cron_check_challenge` | `gamification.challenge` | Daily | `_cron_update()` |
| `ir_cron_update_streaks` | `gamification.streak` | Daily 06:00 | `_cron_update_streaks()` |
| `ir_cron_check_achievements` | `gamification.achievement` | Daily 07:00 | `_cron_check_achievements()` |
| `ir_cron_engagement_snapshot` | `gamification.engagement.snapshot` | Daily 08:00 | `_cron_record_snapshot()` |
| `ir_cron_engagement_nudges` | `res.users` | Daily 09:00 | `_cron_engagement_nudges()` |
| `ir_cron_consolidate` | `gamification.karma.tracking` | Monthly 1st 04:00 | `_consolidate_cron()` |

**Execution order matters:**
1. 06:00 — Streaks (may grant karma)
2. 07:00 — Achievements (may check karma-dependent conditions)
3. 08:00 — Engagement snapshot (captures fresh data after streaks/achievements)
4. 09:00 — Nudges (detects patterns after all data is updated)
5. Daily — Challenge check (goal evaluation + reports)

---

## Test Patterns

### Base Classes

- `TransactionCaseGamification` — sets demo user karma to 2500 **conditionally** (`if not self.user_demo.karma`); skips if karma already set
- `HttpCaseGamification` — same, for HTTP tests

### Test User Creation

```python
from odoo.addons.mail.tests.common import mail_new_test_user

cls.user = mail_new_test_user(
    cls.env,
    login="test_login",
    name="Test Name",
    email="test@example.com",
    karma=0,
    groups="base.group_user",
)
```

### Common Patterns

1. **Patch send_mail** to avoid email sending:
   ```python
   patch_email = patch(
       "odoo.addons.mail.models.mail_template.MailTemplate.send_mail",
       lambda *args, **kwargs: None,
   )
   cls.startClassPatcher(patch_email)
   ```

2. **Override readonly fields** via SQL when needed (e.g., streak counts):
   ```python
   streak.env.cr.execute(
       "UPDATE gamification_streak SET current_count = 6 WHERE id = %s",
       [streak.id],
   )
   streak.invalidate_recordset()
   ```

3. **Date manipulation** with `freezegun`:
   ```python
   from freezegun import freeze_time

   @freeze_time("2026-04-01")
   def test_first_of_month(self):
       ...
   ```

4. **Clean up before each test** when unique constraints exist:
   ```python
   def setUp(self):
       super().setUp()
       self.env["gamification.streak"].search([
           ("user_id", "=", self.test_user.id),
       ]).unlink()
   ```

### Running Tests

```bash
# All gamification tests
> ./odoo.log && ./addons/core/odoo-bin -c ./odoo.conf -d test_db \
    --test-tags '/gamification' -u gamification --stop-after-init --workers=0

# Specific test class
> ./odoo.log && ./addons/core/odoo-bin -c ./odoo.conf -d test_db \
    --test-tags '/gamification:TestStreak' -u gamification --stop-after-init --workers=0

# Check results
grep "tests when loading" ./odoo.log
```

---

## What NOT to Do

1. **Don't create `gamification.badge.user` without checking granting rules.**
   The `create()` method calls `check_granting()` which validates permissions.
   Only `sudo()` bypasses this — used by challenge reward logic and achievement
   unlock logic.

2. **Don't call `_recompute_rank()` on large user sets unnecessarily.**
   The method auto-switches to `_recompute_rank_bulk()` when the user count
   exceeds `len(ranks) * 3`, but callers should still pre-filter to users
   with `karma > 0 or rank_id`.

3. **Don't assume `_ensure_user_streaks` has been called.**
   Streak records are lazily created when `get_gamification_dashboard_data()`
   is called. Code that queries streaks should handle missing records.

4. **Don't use `f-strings` in `_add_karma` reason parameter for logging.**
   The reason is stored in the database, not a log message. Use descriptive
   text with `_()` for translation.

5. **Don't create tracking records with `consolidated=True` manually.**
   The consolidation cron handles this. Manual consolidated records will
   confuse the consolidation logic.

---

## Extension Points

Other modules can extend gamification by:

1. **Creating `gamification.goal.definition` records** — define new measurable
   objectives tied to any model (e.g., CRM leads, project tasks).

2. **Extending `_get_origin_selection_values()`** — add new models as karma
   sources if your module grants karma from a new origin.

3. **Overriding `get_gamification_redirection_data()`** — add buttons to the
   rank-reached email (e.g., "Go to Forum").

4. **Creating `gamification.streak.type` records** — define new streak types
   tied to any model's activity.

5. **Creating `gamification.achievement` records** — define hidden achievements
   with trigger domains on any model.

6. **Creating `gamification.quest` records** — define multi-step narrative
   journeys with ordered steps and prerequisites.

7. **Creating `gamification.skill.tree` + `.node` records** — define branching
   progression paths with karma thresholds and quest-linked unlocks.

8. **Creating `gamification.season` records** — define time-limited themed
   events with exclusive badges and seasonal leaderboards.

9. **Using `gamification.activity._log_*` methods** — add custom events
   to the unified social feed from other modules.

10. **Adding nudge patterns** — extend `_cron_engagement_nudges()` to detect
    module-specific disengagement patterns.
