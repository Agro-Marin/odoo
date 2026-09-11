import "@web/../tests/_framework/mock_server/mock_model";

declare module "@web/../tests/_framework/mock_server/mock_model" {
    interface Model {
        has_activities?: boolean;
        _mail_post_access?: string;
        _to_store_defaults?: (
            string | import("@mail/../tests/mock_server/mail_mock_server").StoreAttr
        )[];
        _to_store?(...args: any[]): any;
    }
}
