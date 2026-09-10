import "luxon";
import { DefaultValidity } from "luxon/src/_util";

declare module "luxon" {
    const _default: any;
    export default _default;
}

declare module "luxon/src/datetime" {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    interface DateTime<IsValid extends boolean = DefaultValidity> {
        readonly ts: number;
    }
}
