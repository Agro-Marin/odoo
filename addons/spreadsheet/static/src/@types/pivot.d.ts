import { OdooPivotRuntimeDefinition } from "@spreadsheet/pivot/odoo_pivot";
import { ORM } from "@web/core/network/orm_service";
import { PivotMeasure } from "@spreadsheet/pivot/odoo_pivot";
import { ServerData } from "@spreadsheet/data_sources/server_data";
import {
    Pivot,
    CommonPivotCoreDefinition,
    PivotCoreDefinition,
} from "@odoo/o-spreadsheet";

declare module "@spreadsheet" {
    export interface OdooPivotCoreDefinition extends CommonPivotCoreDefinition {
        type: "ODOO";
        model: string;
        domain: import("@web/core/domain").DomainRepr;
        context?: Record<string, unknown>;
        actionXmlId: string;
    }

    export type ExtendedPivotCoreDefinition =
        PivotCoreDefinition | OdooPivotCoreDefinition;

    interface OdooPivot<T> extends Pivot<T> {
        type: ExtendedPivotCoreDefinition["type"];
    }
    export interface GFLocalPivot {
        id: string;
        fieldMatching: Record<string, any>;
    }

    export interface OdooField {
        name: string;
        type: string;
        string: string;
        relation?: string;
        searchable?: boolean;
        aggregator?: string;
        store?: boolean;
    }

    export type OdooFields = Record<string, OdooField | undefined>;

    export interface PivotMetaData {
        colGroupBys: string[];
        rowGroupBys: string[];
        activeMeasures: string[];
        resModel: string;
        fields?: Record<string, OdooField | undefined>;
        modelLabel?: string;
        fieldAttrs: any;
    }

    export interface PivotSearchParams {
        groupBy: string[];
        orderBy: string[];
        domain: import("@web/core/domain").DomainRepr;
        context: Record<string, unknown>;
    }

    /* Params used for the odoo pivot model */
    export interface WebPivotModelParams {
        metaData: PivotMetaData;
        searchParams: PivotSearchParams;
    }

    export interface OdooPivotModelParams {
        fields: OdooFields;
        definition: OdooPivotRuntimeDefinition;
        searchParams: {
            domain: import("@web/core/domain").DomainRepr;
            context: Record<string, unknown>;
        };
    }

    export interface PivotModelServices {
        serverData: ServerData;
        orm: ORM;
        getters: OdooGetters;
    }
}
