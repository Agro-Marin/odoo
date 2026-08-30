# ADR-0081: A credential is stored in the vault, and nowhere else

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

`credential.credential` exists and works. It inherits `mixin.encryption`, so a
value is encrypted at rest in `credential_value_encrypted`; it carries a
fingerprint so a presented token can be compared without decrypting anything
(ADR-0017 records what that bought: `base_automation`'s webhook path read the
plaintext per request and shared one rate-limit bucket across every public
sender, so an authenticated webhook stopped working after 100 calls in an hour);
it access-logs every read into `credential.access.log`; and it rate-limits those
reads through `rate.limit.bucket`.

Nineteen modules use it.

**A tree-wide AST pass, measured 2026-08-30, finds 163 `Char`/`Text` fields
holding a third-party secret on a stored model, across 105 modules** — 77 of
them business modules, not localisations. `payment_*` holds 28, `delivery_*` 22,
`pos_*` 13. Three delivery carriers cache an OAuth access token in a plain
`Char` on `delivery.carrier`; twenty-one fiscal modules hold a PAC or authority
password the same way.

None of those values is encrypted, none is access-logged, and every one of them
is readable by anyone who can read the record and dumpable by anyone who can
take a backup.

### The count is 163 and not 311, and the difference is the decision

The obvious pattern — a `Char` whose name matches
`password|secret|api_key|token|…` — matches **311** fields. Acting on that
number would have been wrong in both directions, and four categories are
excluded for reasons that are part of this decision rather than exceptions to it:

| excluded | n | why it is not a credential |
|---|---:|---|
| transient wizard field | 77 | a `TransientModel` field is typed, used and gone; nothing is stored |
| share token | 38 | `access_token`, `invite_token`, `document_token` — a capability **we mint** so a link works. Moving one into an encrypted vault breaks the link it exists to make |
| door | 19 | a `compute`/`inverse` field with no `store=True`, which writes through to a hash or an encrypted blob. `res.users`' `password` and `certificate.certificate`'s `pkcs12_password` are both this: the plain field is the way in, not the store |
| derived | 3 | `*_hash`, `*_masked`, `*_fingerprint` — computed *from* a secret, and the point of them is that they are not it |

The vault's own fields are exempt by construction.

## Decision

**A secret belonging to a third party is stored in `credential.credential` and
referenced by `Many2one`. It is not stored in a `Char` or `Text` field on a
business model.**

Three things follow, and they are the reason this is worth a record rather than
a review comment:

**A door is not a store.** A `compute`/`inverse` `Char` that writes through to an
encrypted or hashed value is the correct shape and stays. The rule is about
where the bytes rest, not about whether the word "password" appears in a field
name.

**A token we mint is not a credential.** A share token authorises the bearer to
see one record; it belongs on that record, is meant to travel in a URL, and
encrypting it would defeat its only purpose. The distinction is *whose secret it
is*.

**A credential is referenced, not copied.** A model that needs one holds a
`Many2one` to it. Copying the value into a local field to avoid a join
reintroduces exactly what this forbids, and the access log stops seeing the read.

## Alternatives considered

**Encrypt in place, per module.** Rejected. `mixin.encryption` could be inherited
by each of the 105 models, and each would then own a key lifecycle, a migration
and a decrypt path. The vault exists so that is written once; a hundred copies of
it is the shape this fork spends its time removing, and the access log — which is
the part that answers *who read this and when* — cannot be assembled from a
hundred separate stores.

**A ratchet rather than default-deny.** Rejected. A ratchet says the number may
not grow; it does not say what a new field should do instead. Every one of the
163 has a correct destination that already exists, so the useful failure message
names it. `edi_vocabulary` and `exchange_vocabulary` settled the same question
the same way.

**Do nothing and rely on review.** Rejected on the measurement. Nineteen modules
found the vault and a hundred and five did not, which is what a convention with
no mechanism looks like after it has been available for a while.

**Widen the rule to share tokens.** Rejected, and it is the alternative most
likely to look attractive to a later reader: they match the same grep, and
"encrypt all the tokens" sounds strictly safer. It is not. A share token in a
vault is a share token that cannot be put in the URL it exists for.

## Consequences

**The 163 do not move in this record.** They are seeded into the gate's
allowlist, each entry naming the field, and come off as modules migrate. The
allowlist is the backlog, ordered by cluster: `payment_*` 28, `delivery_*` 22,
`pos_*` 13.

**A migration is per-module and carries data.** A field holding a live API key
cannot simply be dropped: the value moves into a `credential.credential` record
in a migration script, and the module keeps a `Many2one` where the `Char` was.
That is real work per module and the reason this record does not pretend the
count is a small number.

**Not every module can reference the vault today.** `credential` is a fork
module; a bundled addon that takes a dependency on it makes the vault part of
its install closure. That is intended — the alternative is a bundled addon
storing an API key in the clear — but it means the migration order is a
dependency question, not only a size one.

**The gate cannot see a value assembled at runtime.** A credential read from
`ir.config_parameter`, or passed through a context key, is invisible to a field
scan. This record covers stored fields, which is where the measurement is; it
does not claim to cover every path a secret can take.

## Enforcement

`tooling/architecture/credential_storage.py`, run by `architecture.yml`.
Default-deny over an allowlist, on `edi_vocabulary.py`'s pattern: an AST pass for
a `Char`/`Text` field whose name names a secret, on a non-transient model,
stored, excluding the four categories above. Anything new fails until someone
adds it deliberately.

`--prune` drops an entry whose field is gone, which is how a migration is
recorded. There is no `--update`: a flag that rewrote the list to whatever the
tree holds would let the next one in silently.

The four exclusions are the classifier, so they are tested directly — a wizard
field, a share token, a `compute`/`inverse` door and a `*_hash` companion each
have a case asserting the gate stays quiet, because a gate that fired on those
would be argued down rather than obeyed.

## Amendments

### 2026-08-30 — a fifth exclusion: a cursor is not a credential

The classifier above named four exclusions. There are five. Found the same day,
while choosing the first module to migrate and therefore before any migration
acted on the mistake:

**A cursor the counterparty hands back so the next call resumes a feed is state,
not a secret.** `google_calendar.google_calendar_sync_token` is labelled *"Next
Sync Token"* in its own field definition, is read from `nextSyncToken` in the
response and is sent back as `params['syncToken']`. It authorises nothing, it is
not anybody's secret, and it changes on **every sync** — vaulting it would churn
the encrypted store and its access log for a value whose whole purpose is to be
handed straight back.

`microsoft_calendar.microsoft_calendar_sync_token` is the same field under
another vendor's name. Both came off the backlog, which is 160 entries rather
than the 162 this record was seeded with, against 163 sites.

`CURSOR` — `*_sync_token`, `*_page_token`, `*_next_token`, `*_cursor` — joins
`SHARE`, `DERIVED`, the transient check and the store check in
`credential_storage.py`, with its own tests, including one asserting that a
secret whose name merely *ends* in `token` (`ups_access_token`) still counts.

The decision is unchanged: a credential is stored in the vault. What changed is
one more answer to *what is a credential*, which is the part of this record that
was always going to need the tree to teach it.
