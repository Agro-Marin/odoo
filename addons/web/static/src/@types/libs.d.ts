/**
 * JSDoc type alias: `@param {integer}` maps to `number`.
 * Preserves semantic intent (whole numbers) in documentation.
 */
declare type integer = number;

// Bootstrap 5 globals used by database_manager.js and other public pages
declare const Modal: any;
declare const Tooltip: any;
declare const Dropdown: any;

// declare const Qunit: typeof import("qunit"); => Because we add methods to QUnit, we define our own..
// @ts-expect-error -- QUnit type is augmented by hoot.d.ts, not the npm @types/qunit
declare const QUnit: QUnit;

// @ts-expect-error -- jQuery global is declared without a default export in @types/jquery
declare const $: typeof import("jquery");

// Third-party libraries loaded as globals
declare const ace: any;
declare const ZXing: any;
declare const SignaturePad: any;

// Lazy-loaded third-party ES modules without bundled npm types in this fork
// (pulled in via dynamic ``import()`` from ``@web/core/lib/*``). Declared so the
// dynamic imports type-resolve; their exports are untyped (``any``).
declare module "chart.js";
declare module "chartjs-adapter-luxon";
declare module "@fullcalendar/core";
declare module "@fullcalendar/core/locales-all";
// Chart.js — now a real ES module imported through ``@web/core/lib/chartjs``.
// This ambient global remains ONLY for the two consumers that read
// ``globalThis.Chart`` set by a deliberate installer module rather than
// importing it: the generated ``spreadsheet/.../o_spreadsheet.js`` artifact
// (via ``o_spreadsheet/chartjs_setup.js``) and survey's sync-``setup()`` chart
// interactions (via ``survey/.../interactions/chartjs_setup.js``). All other
// consumers import ``{ Chart }`` from ``@web/core/lib/chartjs``. Typed ``any``
// because the chart.js npm types are not installed in this fork.
declare const Chart: any;

// Web APIs not yet in lib.dom.d.ts
declare class BarcodeDetector {
    constructor(options?: { formats?: string[] });
    detect(source: ImageBitmapSource): Promise<Array<{ rawValue: string; format: string }>>;
    static getSupportedFormats(): Promise<string[]>;
}

// Third-party globals accessed via `window.*`
interface Window {
    ace: any;
    ZXing: any;
    SignaturePad: any;
    Chart: any;
    MozBlob: typeof Blob | undefined;
    WebKitBlob: typeof Blob | undefined;
    clickEverywhere: ((xmlId?: string) => Promise<void>) | undefined;
}
