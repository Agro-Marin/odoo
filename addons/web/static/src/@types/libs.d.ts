/**
 * JSDoc type alias: `@param {integer}` maps to `number`.
 * Preserves semantic intent (whole numbers) in documentation.
 */
declare type integer = number;

declare const Modal: any;
declare const Tooltip: any;
declare const Dropdown: any;

declare const QUnit: QUnit;

declare const $: typeof import("jquery");

declare const ace: any;

declare module "chart.js";
declare module "chartjs-adapter-luxon";
declare module "@fullcalendar/core";
declare module "@fullcalendar/core/locales-all";
declare module "dompurify";
declare module "pdfjs-dist";
declare module "signature_pad";
declare module "zxing-library";
declare const Chart: any;

declare class BarcodeDetector {
    constructor(options?: { formats?: string[] });
    detect(
        source: ImageBitmapSource,
    ): Promise<Array<{ rawValue: string; format: string }>>;
    static getSupportedFormats(): Promise<string[]>;
}

interface Window {
    ace: any;
    Chart: any;
    MozBlob: typeof Blob | undefined;
    WebKitBlob: typeof Blob | undefined;
    clickEverywhere: ((xmlId?: string) => Promise<void>) | undefined;
}
