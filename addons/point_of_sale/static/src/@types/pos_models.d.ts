/**
 * Server-loaded fields on the point-of-sale front-end models.
 *
 * A POS model extends `related_models`' `Base`, which is populated at runtime
 * from whatever `_load_pos_data_fields` sends down; nothing in the JS declares
 * those members, so `tsc` reports TS2339 the moment a model file opts into
 * checking. Declaring them as class fields would be wrong twice over -- a class
 * field initialises to `undefined` at construction and would overwrite the
 * loaded value, and a cast at the use site states the type where the reader is
 * rather than where the contract is.
 *
 * Interface merging is the zero-runtime way to say it: this augments the class
 * declaration itself, so every reader of a ResCompany sees the field and no
 * emitted code changes. Add a member here when a model file starts reading one,
 * and keep the Python side that sends it named in the comment.
 *
 * The bare `export {}` below is load-bearing: `declare module "x"` AUGMENTS an
 * existing module only from inside a module, and declares a new ambient one
 * otherwise. Without it this file silently declares a second, empty
 * `@point_of_sale/app/models/res_company` and the TS2339 stands.
 */
export {};

declare module "@point_of_sale/app/models/res_company" {
    interface ResCompany {
        /** `phone.number` records, sent by `res.company._load_pos_data_read`. */
        phone_ids?: { number: string }[];
    }
}
