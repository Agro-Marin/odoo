# http_routing — Architecture

What this module is, what it owns, and the two mechanisms worth understanding
before editing it: the **multilang ladder** (how a URL picks a language) and the
**URL grammar** (who is allowed to know how a language sits in a path).

> **See also**: `TRAPS.md` — behaviours that look like bugs, or like duplication
> begging to be refactored, and are neither. Read it before "simplifying"
> anything here. `TEST_MAP.md` — which class covers what, and how to run it.

## Module identity

- **Technical name:** `http_routing` · **Depends:** `web` · **Category:** Hidden
- **Role:** turn `ir.http` into a *frontend* router. Everything public-facing
  (`portal`, `website`, and their dependents) sits on top of this.
- **Size:** ~1.3 kLOC of source, ~2.3 kLOC of tests.

It ships exactly **two routes**, both incidental to its real job:

| Route | Why it exists |
|---|---|
| `/website/translations` | serves the frontend's web translations (named once, as `ir_http.FRONTEND_TRANSLATIONS_ROUTE`, because `get_frontend_session_info` hands the same string to the browser) |
| `/web/session/logout` | re-declared `website=True, multilang=False` so logging out from the frontend stays on the frontend |

The module's substance is its **`ir.http` override**: converters, the language
ladder, URL generation, and the frontend error page.

## The request path

```
                    ir.http._match(path)                     models/ir_http.py
                             │
      ┌──────────────────────┴───────────────────────┐
      │ already routed? (hasattr request.is_frontend)│──yes─→ super()._match
      └──────────────────────┬───────────────────────┘
                             │ no
                    _match_and_flag(path)  ── sets is_frontend /
                             │                   is_frontend_multilang
              ┌──────────────┴───────────────┐
       matched, not frontend            NotFound, or frontend
              │                               │
         return rule ──────────────→   collapse "//" runs (301, GET/HEAD only)
                                              │
                                   _resolve_frontend_lang()   ── sets request.lang
                                              │                  under a borrowed
                                              │                  public user
                                   _reroute_for_lang()  ── THE LADDER, below
                                              │
                                   re-match, or reuse the /1 match
                                              │
                                   _pre_dispatch()  ── canonical-slug 301
```

## The ladder (`_reroute_for_lang`)

`request.lang` is resolved first, in priority order: **URL** → `frontend_lang`
cookie → context → site default. The ladder then decides what to do about the
URL itself. Cases are numbered as in `_match`'s docstring.

| # | URL carries a lang | Requested lang | May redirect | Outcome |
|---|---|---|---|---|
| /1 | — | — | — | endpoint is not `website=True` → serve, ladder never runs |
| /2 | no | = default | — | **serve** as-is |
| /3 | no | ≠ default, UA is a bot | — | **serve** as-is, forced to the default lang |
| /4 | no | ≠ default | no | **serve** as-is |
| /5 | no | ≠ default | yes | **303** → `/<lang>` + path |
| /6 | yes, = default | — | yes | **303** → path without the prefix |
| /7 | yes, an alias (`fr_FR`) | — | yes | **301** → `/<url_code>` + path |
| /8 | yes, bare `/<lang>/` | — | yes | **301** → `/<lang>` |
| /9 | yes, canonical *or* redirecting forbidden | — | — | **rewrite**: strip the prefix, serve |

Three properties hold and are pinned by tests:

- **"May redirect" is `GET`/`HEAD` only** (`_REDIRECTABLE_METHODS`). RFC 9110
  lets a client replay a 301/302 on an unsafe method as `GET`, and a 303
  *mandates* it — so redirecting a `POST` silently drops the body. `OPTIONS` is
  excluded too: a browser never follows a redirect on a CORS preflight.
- **Case /9 is the catch-all for unsafe methods.** Its `or not allow_redirect`
  is what makes `POST /fr_FR/x` reach dispatch instead of 404ing on a prefix
  nothing would strip.
- **Every 3xx exits through `_redirect_lang`**, which carries the query string
  and pins the `frontend_lang` cookie to `request.lang` — the same value
  `_frontend_pre_dispatch` writes on the request that is finally served, so the
  redirect and the followed request cannot disagree about the language.

## The URL grammar — who owns what

The recurring failure mode in this file's history is **a second implementation
of "how a language sits in a path"**, drifting from the first. There are now
four primitives, and everything else is required to go through them.

| Primitive | Owns |
|---|---|
| `_url_split_suffix(url)` | RFC 3986 `path[?query][#fragment]`. The fragment starts at the **first** `#`; a `?` after it belongs to the fragment. |
| `_lang_url_prefix(path, url_code)` | gluing a language onto a path (`/` → `/fr`, never `/fr/`) |
| `_lang_url_split(path, url_codes=None)` | the inverse: recognizing a leading `url_code`. Only `url_code`, never the full `code` — `/fr_FR/…` is case /7's business |
| `_frontend_url_codes()` | *what may appear* as a language prefix. `website` narrows it per site, so all three above narrow with it |

Built on them:

| Caller | Question it answers |
|---|---|
| `_url_for` / `_url_lang` | "make this href right for the current page's language" — every href of every frontend page (`ir.qweb._post_processing_att`) |
| `_url_localized` | "give me this URL *in* language X", re-slugging its `<model(…)>` segments |
| `_is_multilang_url` | "is the content at this path translated?" |
| `url_rewrite` | "what does the routing table say this path resolves to?" (ormcached, request-free) |

`_lang_url_split` takes the codes explicitly so a **request-free** caller — a
sitemap builder, a cron, `_is_multilang_url` — can ask at all.

## The error page

```
exception ─→ _get_exception_code_values ─→ (status, values)
                                              │
              status in (404, 403) ───────────┤─→ _serve_fallback()  (website's CMS pages)
                                              │
                             _get_error_template(code, values) ─→ xmlid
                                              │
                             _get_error_html  ─→ (status, html)
```

**Status and template are two decisions, taken by two methods**, and that split
is load-bearing: `_handle_error` keys the `_serve_fallback` attempt off the
*status*, so an override that smuggled a template through the status (as
`website` once did) silently denied a designer the fallback a visitor got.
To render a different page for the same status, override `_get_error_template`.

`_get_error_html` degrades to `http_routing.4xx` / `http_routing.http_error`
when no template matches the status, **keeping the status**. Reporting a 503 as
`418 I'm a teapot` misleads caches, monitors and crawlers alike; that last-resort
branch is for "rendering itself blew up".

### The templates

| xmlid | Role |
|---|---|
| `http_routing.error_page` | the shared 4xx body: heading, hint, then the debug accordion or the error message |
| `http_routing.400`, `http_routing.403`, `http_routing.415`, `http_routing.422`, `http_routing.4xx` | one `t-call` each into `error_page`, carrying only a `t-set` heading and hint |
| `http_routing.404` | its own page (illustration + popular links); `website` inherits it |
| `http_routing.500` | deliberately standalone — **no `frontend_layout`, no assets, no `csrf_token`**, because the cursor may already be broken when it renders |
| `http_routing.http_error` | the generic fallback, also rendered directly by ~20 controllers across other modules — treat its values as a public contract |
| `http_routing.error_message`, `http_routing.http_error_debug` | structural fragments used by the above; the debug accordion renders only under `editable or debug` |

The 4xx pages share one body and differ only by a `t-set` heading and hint. That
text is still an ordinary translatable QWeb term — `TestErrorPageTranslatability`
exists because losing it would not fail any other test, it would quietly serve
English error pages to everyone.

## Slugs

A slug is `[<name>-]<id>`, built from `_SLUG_NAME` / `_SLUG_ID` / `_SLUG_END` so
the matching regex (`_UNSLUG_ROUTE_PATTERN`, non-capturing — werkzeug forbids
groups in a converter regex) and the parsing one (`_UNSLUG_RE`) cannot drift.

`ModelConverter` rejects **id `0`**: it is the one id the grammar accepts that
can never name a record, and nothing downstream catches it (see `TRAPS.md`).
A negative id is retried as its absolute value, because `foo--5` is far more
likely "a record named `foo-`, id 5".
