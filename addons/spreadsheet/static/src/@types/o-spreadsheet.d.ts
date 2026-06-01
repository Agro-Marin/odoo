/**
 * Ambient type declarations for @odoo/o-spreadsheet.
 *
 * o-spreadsheet is bundled at `addons/spreadsheet/static/src/o_spreadsheet/
 * o_spreadsheet.js` (excluded from tsconfig per jsconfig:134) and resolved
 * at runtime via the import map. The npm package `@odoo/o-spreadsheet`
 * exists (current latest 19.1.4) but installing it would pull 4 deps and
 * risk version drift with the bundled source.
 *
 * The 8 sibling `@types/*.d.ts` files in this directory (commands, env,
 * functions, getters, global_filter, models, pivot, plugins) consume this
 * module: they `import { Model, CorePlugin, UID, ... } from
 * "@odoo/o-spreadsheet"`. Without this declaration those imports fail with
 * TS2307 and cascade to TS2339 across spreadsheet code.
 *
 * Types referenced across `.d.ts` files (Model, CorePlugin, UIPlugin,
 * CoreViewPlugin, UID, Registry) are declared explicitly so consumers can
 * import them. The remaining surface (chart helpers, registries,
 * components, stores) is permissive — declaring every export precisely
 * would require porting upstream o-spreadsheet's TypeScript source.
 *
 * Phase 2b of the typecheck CI gate plan
 * (`knowledge/agromarin-knowledge/plans/2026-04-28-typecheck-ci-gate-plan.md`).
 */

declare module "@odoo/o-spreadsheet" {
    // -----------------------------------------------------------------
    // Identity & primitive types
    // -----------------------------------------------------------------
    export type UID = string;
    export type CellErrorType = string;

    // -----------------------------------------------------------------
    // Model — referenced from models.d.ts via Model["config"], Model["getters"]
    // -----------------------------------------------------------------
    export class Model {
        constructor(data?: object, config?: any, revisions?: object[]);
        config: any;
        getters: any;
        dispatch: (...args: any[]) => any;
        exportData(): any;
        joinSession(): void;
        leaveSession(): void;
        [key: string]: any;
    }

    // -----------------------------------------------------------------
    // Plugins — referenced from getters.d.ts, plugins.d.ts
    // Static `getters` array is the OWL-style declaration of plugin getter names.
    // -----------------------------------------------------------------
    export class CorePlugin {
        static getters: readonly string[];
        getters: any;
        [key: string]: any;
    }
    export class UIPlugin {
        static getters: readonly string[];
        getters: any;
        [key: string]: any;
    }
    export class CoreViewPlugin {
        static getters: readonly string[];
        getters: any;
        [key: string]: any;
    }

    // -----------------------------------------------------------------
    // Charts
    // -----------------------------------------------------------------
    export class AbstractChart {
        [key: string]: any;
    }

    // -----------------------------------------------------------------
    // Pivots
    // -----------------------------------------------------------------
    export class Pivot {
        [key: string]: any;
    }
    export interface CommonPivotCoreDefinition {
        [key: string]: any;
    }
    export interface PivotCoreDefinition extends CommonPivotCoreDefinition {
        [key: string]: any;
    }
    export class PivotRuntimeDefinition {
        [key: string]: any;
    }
    export class SpreadsheetPivotTable {
        [key: string]: any;
    }

    // -----------------------------------------------------------------
    // Spreadsheet component & env
    // -----------------------------------------------------------------
    export class Spreadsheet {
        [key: string]: any;
    }
    export interface SpreadsheetChildEnv {
        [key: string]: any;
    }

    // -----------------------------------------------------------------
    // Range
    // -----------------------------------------------------------------
    export interface Range {
        [key: string]: any;
    }
    export interface RangeData {
        [key: string]: any;
    }

    // -----------------------------------------------------------------
    // Eval / errors
    // -----------------------------------------------------------------
    export class EvaluationError extends Error {
        type?: string;
        constructor(message?: string, ...args: any[]);
    }
    export interface EvalContext {
        [key: string]: any;
    }

    // -----------------------------------------------------------------
    // Commands
    // -----------------------------------------------------------------
    export interface CommandResult {
        [key: string]: any;
    }
    export interface DispatchResult {
        [key: string]: any;
    }
    export const readonlyAllowedCommands: readonly any[];

    // -----------------------------------------------------------------
    // Functions / formulas
    // -----------------------------------------------------------------
    export interface AddFunctionDescription {
        [key: string]: any;
    }
    export interface Arg {
        [key: string]: any;
    }
    export function parse(formula: string): any;
    export function tokenize(formula: string): any;
    export function astToFormula(ast: any): string;
    export function iterateAstNodes(ast: any): IterableIterator<any>;
    export const tokenColors: Record<string, string>;
    export const coreTypes: { [key: string]: any };

    // -----------------------------------------------------------------
    // Registry
    // -----------------------------------------------------------------
    export class Registry<T = any> {
        constructor(name?: string);
        add(key: string, value: T, ...args: any[]): Registry<T>;
        get(key: string): T;
        contains(key: string): boolean;
        getAll(): T[];
        getKeys(): string[];
        [key: string]: any;
    }

    // -----------------------------------------------------------------
    // Namespaces — catch-all index signatures so `helpers.foo`,
    // `registries.bar`, `components.Baz` all type-check as `any`.
    // -----------------------------------------------------------------
    export const helpers: { [name: string]: any };
    export const constants: { [name: string]: any };
    export const components: { [name: string]: any };
    export const registries: { [name: string]: any };
    export const stores: { [name: string]: any };
    export const chartHelpers: { [name: string]: any };
    export const hooks: { [name: string]: any };
    export const links: { [name: string]: any };

    // -----------------------------------------------------------------
    // Utilities
    // -----------------------------------------------------------------
    export function load(data: any): any;
    export function getCaretDownSvg(): string;
    export function getCaretUpSvg(): string;
    export function setTranslationMethod(
        translateFn: (term: string, ...args: any[]) => string,
        getTranslatedTerms?: () => any
    ): void;
    export function addFunction(name: string, descr: AddFunctionDescription): void;

    // -----------------------------------------------------------------
    // Misc internals occasionally referenced
    // -----------------------------------------------------------------
    export const __info__: { readonly version: string; [key: string]: any };
    export const SPREADSHEET_DIMENSIONS: { [key: string]: number };
}
