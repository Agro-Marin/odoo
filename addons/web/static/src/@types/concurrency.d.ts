export {};

declare module "@web/core/utils/concurrency" {
    interface Deferred<T = unknown> extends Promise<T> {
        resolve(
            ...args: undefined extends T
                ? [value?: T | PromiseLike<T>]
                : [value: T | PromiseLike<T>]
        ): void;
        reject(reason?: any): void;
    }
}
