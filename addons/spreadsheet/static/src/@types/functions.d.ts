declare module "@spreadsheet" {
    import { AddFunctionDescription, FPayload, EvalContext } from "@odoo/o-spreadsheet";

    export interface CustomFunctionDescription extends AddFunctionDescription {
        compute: (this: ExtendedEvalContext, ...args: FPayload[]) => any;
    }

    interface ExtendedEvalContext extends EvalContext {
        getters: OdooGetters;
    }
}
