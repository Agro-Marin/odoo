import "@mail/model/store";

declare module "@mail/model/store" {
    interface Store {
        /** Installed by makeStore before the store is exposed to consumers. */
        _: import("@mail/model/store_internal").StoreInternal;
    }
}
