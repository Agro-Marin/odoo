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
    export type StoreConstructor<T> = new (...args: never[]) => T;
    export const CellErrorType: {
        readonly NotAvailable: "#N/A";
        readonly InvalidReference: "#REF";
        readonly BadExpression: "#BAD_EXPR";
        readonly CircularDependency: "#CYCLE";
        readonly UnknownFunction: "#NAME?";
        readonly DivisionByZero: "#DIV/0!";
        readonly SpilledBlocked: "#SPILL!";
        readonly GenericError: "#ERROR";
        readonly NullError: "#NULL!";
    };
    export type CellErrorType = (typeof CellErrorType)[keyof typeof CellErrorType];
    export type Maybe<T> = T | null | undefined;
    export type CellValue = string | number | boolean;
    export interface FunctionResultObject {
        value: CellValue;
        format?: string;
    }
    export type FPayload =
        | Maybe<CellValue | FunctionResultObject>
        | Maybe<CellValue | FunctionResultObject>[][];
    export interface CellPosition {
        sheetId: UID;
        col: number;
        row: number;
    }
    export type Cell =
        | { isFormula: false }
        | {
              isFormula: true;
              compiledFormula: { tokens: Token[] };
          };
    export type Granularity = string;
    export type PivotDomain = { field: string; value: CellValue; type: string }[];
    export interface PivotCoreMeasure {
        id: string;
        fieldName: string;
        aggregator: string;
        userDefinedName?: string;
        isHidden?: boolean;
        format?: string;
        computedBy?: string;
        display?: { type: string; fieldName?: string };
    }
    export interface PivotMeasure extends PivotCoreMeasure {
        displayName: string;
        type: string;
        isValid: boolean;
    }
    export interface PivotDimension {
        displayName: string;
        nameWithGranularity: string;
        fieldName: string;
        type: string;
        granularity?: Granularity;
        order?: string;
        isValid: boolean;
    }
    export interface PivotTableColumn {
        fields: string[];
        values: CellValue[];
        width: number;
        offset?: number;
    }
    export interface PivotTableRow {
        fields: string[];
        values: CellValue[];
        indent: number;
    }
    export interface AddPivotCommand {
        type: "ADD_PIVOT";
        pivotId: UID;
        pivot: CommonPivotCoreDefinition;
    }
    export interface UpdatePivotCommand {
        type: "UPDATE_PIVOT";
        pivotId: UID;
        pivot: CommonPivotCoreDefinition;
    }
    export interface CoreCommandMap {
        ADD_PIVOT: AddPivotCommand;
        UPDATE_PIVOT: UpdatePivotCommand;
        REMOVE_PIVOT: { type: "REMOVE_PIVOT"; pivotId: UID };
        DUPLICATE_PIVOT: { type: "DUPLICATE_PIVOT"; pivotId: UID; newPivotId: UID };
    }
    export type CoreCommand = CoreCommandMap[keyof CoreCommandMap];

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
        allowDispatch(command: CoreCommand): string | string[];
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
    export class Pivot<T = PivotRuntimeDefinition> {
        [key: string]: any;
    }
    export interface CommonPivotCoreDefinition {
        [key: string]: any;
    }
    export interface PivotCoreDefinition extends CommonPivotCoreDefinition {
        [key: string]: any;
    }
    export class PivotRuntimeDefinition {
        constructor(
            definition: CommonPivotCoreDefinition,
            fields: Record<
                string,
                { name: string; string: string; type: string; aggregator?: string }
            >,
        );
        columns: PivotDimension[];
        rows: PivotDimension[];
        measures: PivotMeasure[];
        getDimension(nameWithGranularity: string): PivotDimension;
        getMeasure(id: string): PivotMeasure;
        [key: string]: any;
    }
    export class SpreadsheetPivotTable {
        constructor(
            columns: PivotTableColumn[][],
            rows: PivotTableRow[],
            measures: string[],
            fieldsType: Record<string, string | undefined>,
            collapsedDomains?: { COL: PivotDomain[]; ROW: PivotDomain[] },
        );
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
    export interface Token {
        type: string;
        value: string;
    }
    export interface AST {
        type: string;
        value?: any;
        args?: AST[];
    }
    export interface FunctionContext {
        parent: string;
        argPosition: number;
        argsTokens: Token[][];
        args: (AST | undefined)[];
    }
    export interface EnrichedToken extends Token {
        start: number;
        end: number;
        functionContext?: FunctionContext;
    }
    export interface AddFunctionDescription {
        [key: string]: any;
    }
    export interface Arg {
        [key: string]: any;
    }
    export function parse(formula: string): any;
    export function tokenize(formula: string): any;
    export function astToFormula(ast: any): string;
    export function iterateAstNodes(ast: AST): AST[];
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
    export const helpers: {
        toString(data: FPayload): string;
        [name: string]: any;
    };
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
        getTranslatedTerms?: () => any,
    ): void;
    export function addFunction(name: string, descr: AddFunctionDescription): void;

    // -----------------------------------------------------------------
    // Misc internals occasionally referenced
    // -----------------------------------------------------------------
    export const __info__: { readonly version: string; [key: string]: any };
    export const SPREADSHEET_DIMENSIONS: { [key: string]: number };
}
