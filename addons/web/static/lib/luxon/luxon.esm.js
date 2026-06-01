/**
 * ESM adapter for the vendored luxon UMD build.
 *
 * ``luxon.js`` is an IIFE that assigns a ``window.luxon`` global. This
 * adapter re-exports each public API as an ES module so that native ESM
 * callers can ``import { DateTime } from "luxon"`` transparently.
 *
 * The UMD script MUST execute before this module is evaluated — both
 * are loaded via the legacy bundle and the import map respectively, and
 * the legacy bundle is emitted before ``<script type="module">`` tags
 * (or, in esbuild-bundled production, before the bundled module runs).
 *
 * Keep this list in sync with the UMD exports. Adding an export here
 * before the UMD ships it is harmless (it will be ``undefined``), but
 * removing one will break downstream imports.
 */
const g = /** @type {any} */ (globalThis);
const luxon = g.luxon;
if (!luxon) {
    throw new Error(
        "luxon ESM adapter loaded before the UMD luxon.js — check bundle order",
    );
}

export const DateTime = luxon.DateTime;
export const Duration = luxon.Duration;
export const FixedOffsetZone = luxon.FixedOffsetZone;
export const IANAZone = luxon.IANAZone;
export const Info = luxon.Info;
export const Interval = luxon.Interval;
export const InvalidZone = luxon.InvalidZone;
export const Settings = luxon.Settings;
export const SystemZone = luxon.SystemZone;
export const VERSION = luxon.VERSION;
export const Zone = luxon.Zone;

export default luxon;
