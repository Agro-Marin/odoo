declare module "@odoo/owl" {
    export type Env = Record<PropertyKey, any>;

    export interface ComponentConstructor<P = any, E extends Env = Env> {
        new (props: P, env: E, node?: any): Component<P, E>;
        template?: string;
        components?: any;
        props?: Record<string, any> | string[];
        defaultProps?: Record<string, any>;
    }

    export interface AppConfig<E extends Env = Env> {
        env?: E;
        templates?: string | Document | Record<string, string | Element>;
        test?: boolean;
        props?: any;
        getTemplate?: (name: string) => Element | string | null | undefined;
        dev?: boolean;
        warnIfNoStaticProps?: boolean;
        name?: string;
        translatableAttributes?: string[];
        translateFn?: (term: string, ...rest: any[]) => any;
        customDirectives?: Record<
            string,
            (node: Element, value: string, modifiers: string[]) => void
        >;
        globalValues?: Record<string, any>;
    }

    export class App<C extends Component = Component> {
        static apps: Set<App>;
        constructor(component: new (...args: any[]) => C, config?: AppConfig);
        env: Env;
        root: ComponentNode<C> | null;
        scheduler: {
            tasks: Set<unknown>;
            processing: boolean;
            frame: number;
            flush(): void;
            processTasks(): void;
        };
        static registerTemplate(name: string, template: string | Element | Function): void;
        getTemplate(name: string): Function;
        addTemplate(name: string, template: string | Element): void;
        addTemplates(templates: string | Document): void;
        mount(target: HTMLElement | ShadowRoot): Promise<C>;
        destroy(): void;
    }

    export interface ComponentNode<C extends Component = Component> {
        component: C;
        children: Record<string, ComponentNode>;
        app: App;
    }

    export class Component<P = any, E extends Env = Env> {
        static env?: Env;
        static template?: string;
        static components?: any;
        static props?: any;
        static defaultProps?: any;
        constructor(props: P, env: E, node?: any);
        props: P;
        env: E;
        setup(): void;
        render(deep?: boolean): void;
        [key: string]: any;
    }

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
        callback: (nextProps: any) => void | Promise<void>,
    ): void;

    export function reactive<T extends object>(target: T, callback?: () => void): T;
    export function useState<T extends object>(state: T): T;
    export function markRaw<T>(target: T): T;
    export function toRaw<T>(target: T): T;
    export function batched<F extends (...args: any[]) => any>(fn: F): F;

    export function useEnv<E extends Env = Env>(): E;
    export function useChildSubEnv<E extends Env = Env>(env: Partial<E>): void;
    export function useSubEnv<E extends Env = Env>(env: Partial<E>): void;
    export function useComponent<C = Component>(): C;
    export function useEffect(
        effect: (...deps: any[]) => void | (() => void),
        getDependencies?: () => any[],
    ): void;

    export function useExternalListener<K extends keyof WindowEventMap>(
        target: Window,
        type: K,
        handler: (this: Window, ev: WindowEventMap[K]) => any,
        options?: boolean | AddEventListenerOptions,
    ): void;
    export function useExternalListener<K extends keyof DocumentEventMap>(
        target: Document,
        type: K,
        handler: (this: Document, ev: DocumentEventMap[K]) => any,
        options?: boolean | AddEventListenerOptions,
    ): void;
    export function useExternalListener<K extends keyof HTMLElementEventMap>(
        target: HTMLElement,
        type: K,
        handler: (this: HTMLElement, ev: HTMLElementEventMap[K]) => any,
        options?: boolean | AddEventListenerOptions,
    ): void;
    export function useExternalListener(
        target: EventTarget,
        type: string,
        handler: EventListenerOrEventListenerObject,
        options?: boolean | AddEventListenerOptions,
    ): void;

    export interface Ref<T extends Element = HTMLElement> {
        el: T | null;
    }
    export function useRef<T extends Element = HTMLElement>(name: string): Ref<T>;

    export class EventBus<
        EventDetailMap extends Record<string, any> = Record<string, any>,
    > extends EventTarget {
        constructor();
        trigger<K extends keyof EventDetailMap & string>(
            name: K,
            detail?: EventDetailMap[K],
        ): void;
    }

    export function xml(strings: TemplateStringsArray, ...values: any[]): string;

    export interface Markup extends String {
        toString(): string;
        readonly __markup: true;
    }
    export function markup(strings: TemplateStringsArray, ...values: any[]): Markup;
    export function markup(value: string): Markup;

    export function htmlEscape(value: unknown): Markup;

    export function mount<C extends Component>(
        component: ComponentConstructor,
        target: HTMLElement,
        config?: AppConfig,
    ): Promise<C>;

    export function status(
        component: Component,
    ): "new" | "mounted" | "unmounted" | "destroyed";

    export function validate(value: any, schema: any): void;
    export type PropType =
        | BooleanConstructor
        | StringConstructor
        | NumberConstructor
        | ObjectConstructor
        | ArrayConstructor
        | FunctionConstructor
        | (new (...args: never[]) => object)
        | "*";
    export type PropDescription =
        | PropType
        | PropDescription[]
        | {
              type?: PropDescription;
              optional?: boolean;
              value?: unknown;
              element?: PropDescription;
              shape?: Record<string, PropDescription>;
              values?: PropDescription;
              validate?: (value: unknown) => boolean;
          };
    export function validateType(
        key: string,
        value: unknown,
        description: PropDescription,
    ): string | null;

    export function whenReady(): Promise<void>;
    export function whenReady(callback: () => void): void;
    export function loadFile(url: string): Promise<string>;

    export class OwlError extends Error {
        constructor(message: string, options?: ErrorOptions);
    }

    export const blockDom: any;
    export const __info__: {
        readonly url: string;
        readonly version: string;
    };
}
