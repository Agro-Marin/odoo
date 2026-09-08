import "luxon";
import { DefaultValidity } from "luxon/src/_util";

declare module "luxon" {
    const _default: any;
    export default _default;
}

declare module "luxon/src/datetime" {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    interface DateTime<IsValid extends boolean = DefaultValidity> {
        /**
         * Epoch milliseconds. A real runtime field of every DateTime that
         * `@types/luxon` does not surface, so reading it is a type error
         * without this. Unlike `toMillis()` it is not NaN on an invalid
         * DateTime, which is why call sites use it rather than the public
         * accessor.
         */
        readonly ts: number;
    }
}
