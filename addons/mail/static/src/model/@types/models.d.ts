declare module "models" {
    import { Store as StoreClass } from "@mail/model/store";

    export interface Store extends StoreClass {
        Store: StaticMailRecord<Store, typeof StoreClass>;
    }

    type CheckedRecordInput<D, M> = D extends readonly (infer Item)[]
        ? CheckedRecordInput<Item, M>[]
        : D extends object
          ? string extends keyof D
              ? D
              : D & { [K in Exclude<keyof D, keyof M>]: never }
          : D;

    type StaticMailRecord<ClassInterface, JSClassType> = Omit<
        JSClassType,
        "get" | "insert" | "records"
    > & {
        get: (data: object | string | number) => ClassInterface | undefined;
        insert: <D extends object | object[] | string | number = object>(
            data?: D & CheckedRecordInput<D, ClassInterface>,
            options?: object,
        ) => 0 extends 1 & D
            ? any
            : D extends object[]
              ? ClassInterface[]
              : ClassInterface;
        records: { [localId: string]: ClassInterface };
    };

    export type MailModel<M extends string> = string extends M
        ? any
        : M extends keyof Models
          ? Models[M]
          : never;

    export type MailIdExpression = string | [symbol, ...MailIdExpression[]];

    export interface Models {
        Store: Store;
    }
}
