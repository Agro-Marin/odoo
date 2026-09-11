declare module "mock_models" {
    import { IrModelFields as IrModelFieldsClass } from "@web/../tests/_framework/mock_server/mock_models/ir_model_fields";
    import { IrModuleCategory as IrModuleCategoryClass } from "@web/../tests/_framework/mock_server/mock_models/ir_module_category";
    import { ResGroups as ResGroupsClass } from "@web/../tests/_framework/mock_server/mock_models/res_groups";
    import { ResGroupsPrivilege as ResGroupsPrivilegeClass } from "@web/../tests/_framework/mock_server/mock_models/res_groups_privilege";

    export interface IrModelFields extends IrModelFieldsClass {}
    export interface IrModuleCategory extends IrModuleCategoryClass {}
    export interface ResGroups extends ResGroupsClass {}
    export interface ResGroupsPrivilege extends ResGroupsClassPrivilege {}

    export interface Models {
        "ir.model.fields": IrModelFields;
        "ir.module.category": IrModuleCategory;
        "res.groups": ResGroups;
        "res.groups.privilege": ResGroupsPrivilege;
    }
}
