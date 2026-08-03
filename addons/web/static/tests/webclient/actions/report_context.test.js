// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getReportContext, getReportUrl } from "@web/webclient/actions/reports/utils";

/**
 * A report renders under the user's context with the ACTION's on top.
 *
 * The two halves of one action used to disagree: the html preview's url carried
 * ``user.context`` alone, while the pdf download posted ``{...user, ...action}``.
 * An action carrying ``lang`` therefore previewed in one language and printed in
 * another. ``preprocessAction`` does not fold ``user.context`` into
 * ``action.context`` — the former is only the evaluation context — so neither
 * one alone is the render context.
 */
describe.current.tags("desktop");

const USER_CONTEXT = { lang: "en_US", tz: "UTC", uid: 2 };

/**
 * @param {Record<string, any>} [context]
 * @param {any} [data]
 * @returns {any} a ReportAction-shaped literal; the helper only fills the keys
 *   these tests read, so it is handed over untyped rather than widened.
 */
function reportAction(context, data) {
    return {
        type: "ir.actions.report",
        report_name: "some.report",
        report_type: "qweb-pdf",
        context,
        data,
    };
}

/** @param {string} url */
function contextOf(url) {
    const query = new URLSearchParams(url.split("?")[1] || "");
    const raw = query.get("context");
    return raw ? JSON.parse(raw) : null;
}

test("the render context is the user's, with the action's on top", () => {
    const context = getReportContext(
        reportAction({ lang: "es_MX", custom_key: 7 }),
        USER_CONTEXT,
    );
    expect(context).toEqual({ lang: "es_MX", tz: "UTC", uid: 2, custom_key: 7 });
});

test("html preview and pdf download agree on the context, without data", () => {
    const action = reportAction({ lang: "es_MX", custom_key: 7 });
    const htmlContext = contextOf(getReportUrl(action, "html", USER_CONTEXT));
    const downloadContext = getReportContext(action, USER_CONTEXT);
    expect(htmlContext).toEqual(downloadContext);
    expect(htmlContext.lang).toBe("es_MX");
    expect(htmlContext.tz).toBe("UTC");
});

test("html preview and pdf download agree on the context, with data", () => {
    const action = reportAction({ lang: "es_MX" }, { some: "payload" });
    const htmlContext = contextOf(getReportUrl(action, "html", USER_CONTEXT));
    const downloadContext = getReportContext(action, USER_CONTEXT);
    expect(htmlContext).toEqual(downloadContext);
    expect(htmlContext.tz).toBe("UTC");
});

test("active_ids still select the records, and come from either context", () => {
    const action = reportAction({ active_ids: [4, 5] });
    expect(getReportUrl(action, "html", USER_CONTEXT)).toMatch(
        /^\/report\/html\/some\.report\/4,5\?/,
    );
    expect(getReportUrl(action, "pdf", USER_CONTEXT)).toBe(
        "/report/pdf/some.report/4,5",
    );
});

test("an action with no context of its own still renders under the user's", () => {
    expect(
        contextOf(getReportUrl(reportAction(undefined), "html", USER_CONTEXT)),
    ).toEqual(USER_CONTEXT);
});
