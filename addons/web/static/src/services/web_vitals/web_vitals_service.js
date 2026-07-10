// @ts-check
/** @odoo-module native */

/** @module @web/services/web_vitals/web_vitals_service - Real User Monitoring (RUM) for Core Web Vitals via sendBeacon on pagehide */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

const ENDPOINT = "/web/observability/cwv";

/**
 * Service that captures Core Web Vitals via PerformanceObserver and beacons
 * them to the server when the page is hidden or unloaded.  Reuses the
 * ``pagehide`` + ``navigator.sendBeacon`` pattern proven in
 * ``record_save.js`` (``save()``) for urgent saves.
 *
 * Captures: LCP (Largest Contentful Paint), FCP (First Contentful Paint),
 * CLS (Cumulative Layout Shift), TTFB (Time To First Byte), and INP
 * (Interaction to Next Paint — reported as the worst-observed interaction
 * duration; see the P100-vs-P98 note near the INP observer below).
 */
export const webVitalsService = {
    /** Service has no dependencies; runs once at startup, then passively observes. */
    start() {
        if (!browser.PerformanceObserver) {
            // Old browser without PerformanceObserver (pre-2016).  Nothing to do —
            // we deliberately do not feature-detect each metric type because the
            // PerformanceObserver entry types we use have shipped in every
            // browser-support-matrix browser since 2018.
            return;
        }

        // Sample-rate gate.  Per-session, not per-beacon: roll the dice once
        // at start, either capture everything or capture nothing.  This keeps
        // the per-URL distribution clean (a sampled session contributes a
        // full pageview's worth of metrics or none).  Default 1.0 in dev;
        // production ratchets via the ``web.cwv.sample_rate`` config param,
        // which the server exposes via ``_base_session_info``.
        const rawRate = Number(session.cwv_sample_rate);
        const sampleRate = Number.isFinite(rawRate)
            ? Math.max(0, Math.min(1, rawRate))
            : 1;
        if (sampleRate < 1 && Math.random() >= sampleRate) {
            return;
        }

        /** @type {{ lcp?: number, fcp?: number, cls?: number, ttfb?: number, inp?: number }} */
        const metrics = {};

        // TTFB from Navigation Timing — synchronous, available immediately.
        try {
            const nav = /** @type {any} */ (
                browser.performance.getEntriesByType("navigation")[0]
            );
            if (nav && nav.responseStart > 0 && nav.requestStart >= 0) {
                metrics.ttfb = Math.max(0, nav.responseStart - nav.requestStart);
            }
        } catch {
            // ignore — browser without nav-timing v2 (very rare)
        }

        // FCP — single-shot: disconnect after first paint entry.
        try {
            const fcpObserver = new browser.PerformanceObserver((entries) => {
                for (const entry of entries.getEntries()) {
                    if (entry.name === "first-contentful-paint") {
                        metrics.fcp = entry.startTime;
                        fcpObserver.disconnect();
                        break;
                    }
                }
            });
            fcpObserver.observe({ type: "paint", buffered: true });
        } catch {
            // ignore — browser without paint timing
        }

        // LCP — keeps observing; latest entry wins because LCP can update as
        // larger elements paint later.  Per W3C, LCP is finalized at first user
        // input or page hide; we sample whichever value is current at flush time.
        try {
            const lcpObserver = new browser.PerformanceObserver((entries) => {
                const list = entries.getEntries();
                const last = list[list.length - 1];
                if (last) {
                    metrics.lcp = last.startTime;
                }
            });
            lcpObserver.observe({
                type: "largest-contentful-paint",
                buffered: true,
            });
        } catch {
            // ignore
        }

        // CLS — sum of layout-shift values over the page lifetime, excluding
        // shifts within 500ms of user input (which are intentional).  This
        // matches the W3C definition of "session-window CLS"... approximately.
        // For the canonical session-window calculation, vendor web-vitals.
        try {
            let clsValue = 0;
            const clsObserver = new browser.PerformanceObserver((entries) => {
                for (const entry of entries.getEntries()) {
                    const e = /** @type {any} */ (entry);
                    if (!e.hadRecentInput) {
                        clsValue += e.value;
                    }
                }
                metrics.cls = clsValue;
            });
            clsObserver.observe({ type: "layout-shift", buffered: true });
        } catch {
            // ignore
        }

        // INP — Track the worst (longest) interaction over the page lifetime.
        // Entries with ``interactionId === 0`` are non-interactive events
        // (programmatic, hover) and don't count toward INP.
        // ``durationThreshold: 40`` skips events shorter than 40ms — these
        // are below the perceptible-latency floor and would only add noise.
        //
        // The P100 (worst-observed) reducer here is a strict upper bound on
        // the canonical P98 INP, so a scalar running max suffices — the P98
        // reducer will need the per-interactionId grouping back.  Swap for
        // the sliding-window reducer when vendoring web-vitals; the wire
        // schema does not change.
        try {
            const inpObserver = new browser.PerformanceObserver((entries) => {
                for (const entry of entries.getEntries()) {
                    const e = /** @type {any} */ (entry);
                    if (!e.interactionId) {
                        continue;
                    }
                    if (e.duration > (metrics.inp || 0)) {
                        metrics.inp = e.duration;
                    }
                }
            });
            // ``durationThreshold`` is part of the Event Timing spec extension
            // for ``PerformanceObserverInit`` but is not yet in the standard
            // TS DOM lib (lands with PerformanceEventTiming). Cast keeps the
            // observe call type-clean.
            inpObserver.observe(
                /** @type {any} */ ({
                    type: "event",
                    buffered: true,
                    durationThreshold: 40,
                }),
            );
        } catch {
            // ignore — Safari ≤16 ships event-timing without ``interactionId``
            // (lands in 16.4); pre-Chromium-96 lacks the entry type entirely.
        }

        // Idempotent flush: pagehide AND visibilitychange-to-hidden can both
        // fire on mobile, but we only want to send once.
        let flushed = false;
        function flush() {
            if (flushed) {
                return;
            }
            flushed = true;
            if (!Object.keys(metrics).length) {
                return;
            }
            try {
                const payload = {
                    // pathname only — ``location.search`` can carry record ids
                    // and other PII that Web-Vitals aggregation does not need,
                    // so it must not even leave the browser (the /web/cwv
                    // controller additionally strips any query string as
                    // defense-in-depth for stale cached clients).
                    url: browser.location.pathname,
                    user_agent: browser.navigator.userAgent.slice(0, 500),
                    ...metrics,
                };
                const blob = new Blob([JSON.stringify(payload)], {
                    type: "application/json",
                });
                browser.navigator.sendBeacon(ENDPOINT, blob);
            } catch {
                // RUM must never throw into user code.  Drop silently.
            }
        }

        // pagehide is the modern unload signal (replaces beforeunload, which is
        // unreliable on mobile and breaks BFCache).  visibilitychange to hidden
        // also fires when a tab is backgrounded — capture metrics then in case
        // the user never returns.
        browser.addEventListener("pagehide", flush);
        browser.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "hidden") {
                flush();
            }
        });
    },
};

registry.category("services").add("web_vitals", webVitalsService);
