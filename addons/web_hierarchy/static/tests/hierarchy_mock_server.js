import { beforeEach } from "@odoo/hoot";
import { onRpc } from "@web/../tests/web_test_helpers";

function hierarchyRead({ model, args, kwargs }) {
    const [domain, specification, parentFieldName, childFieldName, order, onlyRoots] =
        args;
    const readKwargs = { ...kwargs, order };
    if (!(parentFieldName in specification)) {
        specification[parentFieldName] = { fields: { display_name: {} } };
    }
    const search = (searchDomain) =>
        this.env[model].web_search_read(searchDomain, specification, readKwargs)
            ?.records || [];

    let records = search(
        onlyRoots ? [[parentFieldName, "=", false], ...domain] : domain,
    );
    if (!records.length && onlyRoots) {
        records = search(domain);
    }
    if (!records.length) {
        return [];
    }
    const isFocusedOnOneRecord = records.length === 1;
    if (isFocusedOnOneRecord) {
        const record = records[0];
        const parentResId = record[parentFieldName] && record[parentFieldName].id;
        records.push(
            ...search(
                parentResId
                    ? [
                          "&",
                          ["id", "!=", record.id],
                          "|",
                          ["id", "=", parentResId],
                          [parentFieldName, "in", [parentResId, record.id]],
                      ]
                    : [
                          [parentFieldName, "=", record.id],
                          ["id", "!=", record.id],
                      ],
            ),
        );
    }
    if (childFieldName) {
        return records;
    }
    const parentResIds = records
        .filter((rec) => rec[parentFieldName])
        .map((rec) => rec[parentFieldName].id);
    const resIdsNeedingChildIds = records
        .map((rec) => rec.id)
        .filter((resId) => !isFocusedOnOneRecord || !parentResIds.includes(resId));
    const groups = this.env[model].formatted_read_group({
        ...kwargs,
        domain: [[parentFieldName, "in", resIdsNeedingChildIds]],
        groupby: [parentFieldName],
        aggregates: ["id:array_agg"],
    });
    const childIdsPerResId = new Map(
        groups.map((group) => [group[parentFieldName][0], group["id:array_agg"]]),
    );
    for (const record of records) {
        if (childIdsPerResId.has(record.id)) {
            record.__child_ids__ = childIdsPerResId.get(record.id);
        }
    }
    return records;
}

beforeEach(() => onRpc("hierarchy_read", hierarchyRead), { global: true });
