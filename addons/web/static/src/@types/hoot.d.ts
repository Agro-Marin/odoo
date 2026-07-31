declare module "@odoo/hoot" {
    export * from "@web/../lib/hoot/hoot";

    /**
     * Configurator methods available on `test` and `describe`.
     *
     * These are added at runtime via Object.defineProperty in
     * Runner._addConfigurators, which TypeScript cannot track.
     */
    interface HootConfigurators {
        readonly debug: HootConfigurators & ((...args: any[]) => any);
        readonly only: HootConfigurators & ((...args: any[]) => any);
        readonly skip: HootConfigurators & ((...args: any[]) => any);
        readonly todo: HootConfigurators & ((...args: any[]) => any);
        readonly config: (...configs: any[]) => HootConfigurators;
        readonly current: HootConfigurators;
        readonly multi: (count: number) => HootConfigurators;
        readonly tags: (...tagNames: string[]) => HootConfigurators;
        readonly timeout: (ms: number) => HootConfigurators;
    }

    interface TestFunction extends HootConfigurators {
        // `void`, not `void | PromiseLike<void>`: TS only applies its
        // return-value-ignored rule when the target return type is exactly
        // `void`, so the union form rejects both an async body and a concise
        // arrow like `() => expect(x).toBe(y)`. Plain `void` accepts every
        // shape and still says the runner discards the value (it awaits it).
        (name: string, fn: () => void): any;
    }

    interface DescribeFunction extends HootConfigurators {
        (name: string | Iterable<string>, fn: (() => void) | string): any;
    }

    export const test: TestFunction;
    export const describe: DescribeFunction;
}

declare module "@odoo/hoot-dom" {
    export * from "@web/../lib/hoot-dom/hoot-dom";
}
