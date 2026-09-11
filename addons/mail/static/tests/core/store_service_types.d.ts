declare module "services" {
    interface Services {
        store: {
            start: (
                env: import("@web/env").OdooEnv,
            ) => import("@mail/model/store").Store & Record<string, any>;
        };
    }
}
