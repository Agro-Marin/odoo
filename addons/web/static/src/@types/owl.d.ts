/**
 * Ambient type declarations for @odoo/owl.
 *
 * OWL is bundled at `static/lib/owl/owl.es.js` (version 2.8.2) and resolved
 * at runtime via the import map emitted by `ir_qweb._get_native_module_nodes()`
 * (see `addons/web/machine_doc_v1/ESM_BUNDLING.md`). The npm package
 * `@odoo/owl` is NOT installed — installing it would pull jsdom + ~30
 * transitive packages and risk version drift with the bundled runtime.
 * This file declares the public API directly so `tsc --noEmit` can
 * resolve `import { ... } from "@odoo/owl"` without those costs.
 *
 * Source of truth for the export list: the `export { ... }` statement at
 * the end of `owl.es.js`. Adapted for the typing patterns this codebase
 * actually uses (component generics simplified, hooks left loosely typed
 * where upstream OWL keeps internals private). If the bundled OWL is
 * upgraded, re-extract the export list and update this file.
 */

declare module "@odoo/owl" {
    // -----------------------------------------------------------------
    // Core types
    // -----------------------------------------------------------------
    export type Env = Record<string, any>;

    export interface ComponentConstructor<P = any, E extends Env = Env> {
        new (props: P, env: E, node?: any): Component<P, E>;
        template?: string;
        components?: Record<string, ComponentConstructor>;
        props?: Record<string, any> | string[];
        defaultProps?: Record<string, any>;
    }

    // -----------------------------------------------------------------
    // App
    // -----------------------------------------------------------------
    export interface AppConfig<E extends Env = Env> {
        env?: E;
        getTemplate?: (name: string) => Element | string | null | undefined;
        dev?: boolean;
        warnIfNoStaticProps?: boolean;
        name?: string;
        translatableAttributes?: string[];
        // Loose signature — the fork's `appTranslateFn` takes
        // (source, moduleName, ...substitutions) and returns
        // `string | Markup | TranslatedString`, where `TranslatedString`
        // is a fork-private value-of-able class. Vanilla OWL only invokes
        // this as `translateFn(term, ctx?)`, but the type declaration must
        // be permissive enough to accept the richer fork signature.
        translateFn?: (term: string, ...rest: any[]) => any;
        customDirectives?: Record<
            string,
            (node: Element, value: string, modifiers: string[]) => void
        >;
        globalValues?: Record<string, any>;
    }

    export class App<C extends Component = Component> {
        constructor(component: ComponentConstructor, config?: AppConfig);
        env: Env;
        mount(target: HTMLElement | ShadowRoot): Promise<C>;
        destroy(): void;
    }

    // -----------------------------------------------------------------
    // Component
    // -----------------------------------------------------------------
    // Static fields are intentionally typed loosely (`any`) instead of
    // `Record<string, ComponentConstructor>` etc. Subclasses commonly assign
    // specific object literals (`static components = { TimePicker }`,
    // `static props = { ...standardFieldProps, foo: String }`) which TS does
    // not widen to an index-signature type — the strict variance produces
    // TS2417 ("class static side incorrectly extends"). Upstream OWL uses
    // a runtime Schema type that papers over this in its own source; we
    // accept the loss of static-field type info here as the right trade.
    export class Component<P = any, E extends Env = Env> {
        static template?: string;
        static components?: any;
        static props?: any;
        static defaultProps?: any;
        constructor(props: P, env: E, node?: any);
        props: P;
        env: E;
        readonly el: HTMLElement | undefined;
        setup(): void;
        render(deep?: boolean): void;
        // Index signature: OWL components accumulate state/refs/services via
        // `setup()`, which TypeScript cannot track as instance fields without
        // explicit class-field declarations on every subclass. The fork's
        // tsconfig is `strict: false / noImplicitAny: false`, and OWL's
        // actual runtime allows arbitrary `this.foo = bar` assignment, so
        // we surface that here. The cost is that typos like
        // `comp.foO` no longer fail on a base-class shape — that's an
        // accepted trade until the team graduates to stricter type-check.
        [key: string]: any;
    }

    // -----------------------------------------------------------------
    // Lifecycle hooks
    // -----------------------------------------------------------------
    export function onError(callback: (error: any) => void): void;
    export function onMounted(callback: () => void | Promise<void>): void;
    export function onPatched(callback: () => void): void;
    export function onRendered(callback: () => void): void;
    export function onWillDestroy(callback: () => void | Promise<void>): void;
    export function onWillPatch(callback: () => void): void;
    export function onWillRender(callback: () => void): void;
    export function onWillStart(callback: () => void | Promise<void>): void;
    export function onWillUnmount(callback: () => void | Promise<void>): void;
    export function onWillUpdateProps(
        callback: (nextProps: any) => void | Promise<void>
    ): void;

    // -----------------------------------------------------------------
    // Reactivity
    // -----------------------------------------------------------------
    export function reactive<T extends object>(target: T, callback?: () => void): T;
    export function useState<T extends object>(state: T): T;
    export function markRaw<T>(target: T): T;
    export function toRaw<T>(target: T): T;
    export function batched<F extends (...args: any[]) => any>(fn: F): F;

    // -----------------------------------------------------------------
    // Env / component / effect hooks
    // -----------------------------------------------------------------
    export function useEnv<E extends Env = Env>(): E;
    export function useChildSubEnv<E extends Env = Env>(env: Partial<E>): void;
    export function useSubEnv<E extends Env = Env>(env: Partial<E>): void;
    export function useComponent<C = Component>(): C;
    export function useEffect(
        effect: (...deps: any[]) => void | (() => void),
        getDependencies?: () => any[]
    ): void;

    // useExternalListener — typed overloads for window/document/element events,
    // plus a permissive fallback for arbitrary EventTargets.
    export function useExternalListener<K extends keyof WindowEventMap>(
        target: Window,
        type: K,
        handler: (this: Window, ev: WindowEventMap[K]) => any,
        options?: boolean | AddEventListenerOptions
    ): void;
    export function useExternalListener<K extends keyof DocumentEventMap>(
        target: Document,
        type: K,
        handler: (this: Document, ev: DocumentEventMap[K]) => any,
        options?: boolean | AddEventListenerOptions
    ): void;
    export function useExternalListener<K extends keyof HTMLElementEventMap>(
        target: HTMLElement,
        type: K,
        handler: (this: HTMLElement, ev: HTMLElementEventMap[K]) => any,
        options?: boolean | AddEventListenerOptions
    ): void;
    export function useExternalListener(
        target: EventTarget,
        type: string,
        handler: EventListenerOrEventListenerObject,
        options?: boolean | AddEventListenerOptions
    ): void;

    // -----------------------------------------------------------------
    // Refs
    // -----------------------------------------------------------------
    export interface Ref<T extends Element = HTMLElement> {
        el: T | null;
    }
    export function useRef<T extends Element = HTMLElement>(name: string): Ref<T>;

    // -----------------------------------------------------------------
    // EventBus
    // -----------------------------------------------------------------
    export class EventBus<
        EventDetailMap extends Record<string, any> = Record<string, any>,
    > extends EventTarget {
        constructor();
        trigger<K extends keyof EventDetailMap & string>(
            name: K,
            detail?: EventDetailMap[K]
        ): void;
    }

    // -----------------------------------------------------------------
    // Templates / markup / escape
    // -----------------------------------------------------------------
    export function xml(strings: TemplateStringsArray, ...values: any[]): string;

    export interface Markup {
        toString(): string;
        readonly __markup: true;
    }
    export function markup(strings: TemplateStringsArray, ...values: any[]): Markup;
    export function markup(value: string): Markup;

    export function htmlEscape(value: string): string;

    // -----------------------------------------------------------------
    // Mount / status
    // -----------------------------------------------------------------
    export function mount<C extends Component>(
        component: ComponentConstructor,
        target: HTMLElement,
        config?: AppConfig
    ): Promise<C>;

    export function status(
        component: Component
    ): "new" | "mounted" | "unmounted" | "destroyed";

    // -----------------------------------------------------------------
    // Validation
    // -----------------------------------------------------------------
    export function validate(value: any, schema: any): void;
    export function validateType(value: any, type: any): boolean;

    // -----------------------------------------------------------------
    // Utilities
    // -----------------------------------------------------------------
    export function whenReady(): Promise<void>;
    export function whenReady(callback: () => void): void;
    export function loadFile(url: string): Promise<string>;

    // -----------------------------------------------------------------
    // Errors and internals
    // -----------------------------------------------------------------
    export class OwlError extends Error {
        constructor(message: string, options?: ErrorOptions);
    }

    export const blockDom: any;
    export const __info__: {
        readonly url: string;
        readonly version: string;
    };
}
