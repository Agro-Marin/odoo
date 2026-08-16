/** @odoo-module native */
export function simplifyString(str) {
    return (
        str
            ?.trim()
            .toLowerCase()
            .replace(/[^a-zA-Z\d]/g, "") ?? ""
    );
}

function stringMatch(query, str) {
    // Score against the SIMPLIFIED length: the query was simplified before
    // being compared, so dividing by the raw length scored `res.partner` below
    // an identical match on `respartner` for no reason a reader could see.
    const simplified = simplifyString(str);
    if (simplified.includes(query)) {
        return query.length / simplified.length;
    } else {
        return 0;
    }
}

export function search(models, query, filters) {
    query = simplifyString(query);
    if (!query) {
        return [];
    }

    const results = [];
    for (const model of models) {
        const modelMatch = stringMatch(query, model.model);
        const modelNameMatch = stringMatch(query, model.name);
        if (filters.models && (modelMatch > 0 || modelNameMatch > 0)) {
            results.push({
                priority: 10 * Math.max(modelMatch, modelNameMatch),
                model,
                type: "model",
                label: model.name,
                path: model.model,
            });
        }

        if (filters.fields) {
            for (const field in model.fields) {
                const path = `${model.model}/${field}`;
                const pathMatch = stringMatch(query, path);
                const fieldMatch = stringMatch(query, field);
                const labelMatch = stringMatch(query, model.fields[field].string);
                if (pathMatch > 0 || fieldMatch > 0 || labelMatch > 0) {
                    results.push({
                        priority: 5 * Math.max(pathMatch, fieldMatch, labelMatch),
                        model,
                        field,
                        type: "field",
                        label: model.fields[field].string,
                        path,
                    });
                }
            }
        }

        if (filters.methods) {
            for (const method of model.methods) {
                const path = `${model.model}/${method}`;
                const pathMatch = stringMatch(query, path);
                const methodMatch = stringMatch(query, method);
                if (pathMatch > 0 || methodMatch > 0) {
                    results.push({
                        priority: 5 * Math.max(pathMatch, methodMatch),
                        model,
                        method,
                        type: "method",
                        label: method,
                        path: path,
                    });
                }
            }
        }
    }

    results.sort((a, b) => {
        if (a.priority === b.priority) {
            return a.label.localeCompare(b.label);
        } else {
            return b.priority - a.priority;
        }
    });

    return results;
}
