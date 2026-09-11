declare module "models" {
    import { Store as StoreClass } from "@mail/model/store";

    export interface Store extends StoreClass {
        Store: StaticMailRecord<Store, typeof StoreClass>;
    }

    type StaticMailRecord<ClassInterface, JSClassType> = Omit<
        JSClassType,
        "get" | "insert" | "records"
    > & {
        get: (data: any) => ClassInterface;
        insert: <D extends object | object[] | string | number = object>(
            data?: D,
            options?: object,
        ) => 0 extends 1 & D
            ? any
            : D extends object[]
              ? ClassInterface[]
              : ClassInterface;
        records: { [localId: string]: ClassInterface };
    };

    export type MailModel<M extends string> = M extends keyof Models ? Models[M] : any;

    export type MailIdExpression = string | [symbol, ...MailIdExpression[]];

    export interface Models {
        Store: Store;
    }
}
