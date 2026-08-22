// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    buildActionInfo,
    buildActionViews,
    buildViewInfo,
} from "@web/webclient/actions/action_info_builders";

/**
 * @param {Object} [overrides]
 */
function makeFakeAm(overrides = {}) {
    const calls = { pushState: 0, switchView: [], doAction: [] };
    const am = {
        pushState: () => calls.pushState++,
        _getView: () => null,
        switchView: (type, props, options) =>
            calls.switchView.push({ type, props, options }),
        doAction: (action, options) => calls.doAction.push({ action, options }),
        ...overrides,
    };
    am.__calls = calls;
    return am;
}

const LIST = {
    type: "list",
    icon: "oi-view-list",
    display_name: "List",
    multiRecord: true,
};
const KANBAN = {
    type: "kanban",
    icon: "oi-view-kanban",
    display_name: "Kanban",
    multiRecord: true,
};
const FORM = {
    type: "form",
    icon: "oi-view-form",
    display_name: "Form",
    multiRecord: false,
};

/** @param {Object} [overrides] */
function makeAction(overrides = {}) {
    return {
        id: 1,
        name: "Partners",
        res_model: "partner",
        views: [
            [false, "list"],
            [false, "form"],
            [false, "search"],
        ],
        ...overrides,
    };
}

describe.current.tags("desktop");

test("client props carry the action and its id alongside the caller's props", async () => {
    const action = { id: 7, name: "Some Client Action" };
    const { props } = buildActionInfo(action, { custom: 1 }, makeFakeAm());
    expect(props.custom).toBe(1);
    expect(props.action).toBe(action);
    expect(props.actionId).toBe(7);
});

test("client displayName prefers display_name, then name, then empty", async () => {
    const am = makeFakeAm();
    expect(buildActionInfo({ display_name: "D", name: "N" }, {}, am).displayName).toBe(
        "D",
    );
    expect(buildActionInfo({ name: "N" }, {}, am).displayName).toBe("N");
    expect(buildActionInfo({}, {}, am).displayName).toBe("");
});

test("active_id is left UNDEFINED rather than defaulted to false", async () => {
    const { currentState } = buildActionInfo({ id: 1 }, {}, makeFakeAm());
    expect("active_id" in currentState).toBe(true);
    expect(currentState.active_id).toBe(undefined);

    const withActive = buildActionInfo(
        { id: 1, context: { active_id: 4 } },
        {},
        makeFakeAm(),
    );
    expect(withActive.currentState.active_id).toBe(4);
});

test("resId, unlike active_id, DOES default to false", async () => {
    const am = makeFakeAm();
    expect(buildActionInfo({ id: 1 }, {}, am).currentState.resId).toBe(false);
    expect(buildActionInfo({ id: 1 }, { resId: 9 }, am).currentState.resId).toBe(9);
});

test("updateActionState pushes a url only when the state actually changed", async () => {
    const am = makeFakeAm();
    const { props, currentState } = buildActionInfo({ id: 1 }, { resId: 3 }, am);
    const controller = { isMounted: true };

    props.updateActionState(controller, { resId: 3 });
    expect(am.__calls.pushState).toBe(0);

    props.updateActionState(controller, { resId: 4 });
    expect(am.__calls.pushState).toBe(1);
    expect(currentState.resId).toBe(4);
});

test("updateActionState never pushes for a dialog, or before the controller mounts", async () => {
    const am = makeFakeAm();
    const dialog = buildActionInfo({ id: 1, target: "new" }, {}, am);
    dialog.props.updateActionState({ isMounted: true }, { resId: 5 });
    expect(am.__calls.pushState).toBe(0);
    expect(dialog.currentState.resId).toBe(5);

    const inline = buildActionInfo({ id: 1 }, {}, am);
    inline.props.updateActionState({ isMounted: false }, { resId: 5 });
    expect(am.__calls.pushState).toBe(0);
});

test("the view switcher only offers views of the same arity", async () => {
    const { config } = buildViewInfo(
        LIST,
        makeAction(),
        [LIST, KANBAN, FORM],
        {},
        makeFakeAm(),
    );
    expect(config.viewSwitcherEntries.map((e) => e.type)).toEqual(["list", "kanban"]);
});

test("the current view is the only one flagged active", async () => {
    const { config } = buildViewInfo(
        KANBAN,
        makeAction(),
        [LIST, KANBAN],
        {},
        makeFakeAm(),
    );
    const active = config.viewSwitcherEntries.filter((e) => e.active);
    expect(active.map((e) => e.type)).toEqual(["kanban"]);
});

test("a string group_by is normalised to an array, an empty one to []", async () => {
    const am = makeFakeAm();
    const build = (group_by) =>
        buildViewInfo(LIST, makeAction({ context: { group_by } }), [LIST], {}, am).props
            .groupBy;
    expect(build("stage_id")).toEqual(["stage_id"]);
    expect(build("")).toEqual([]);
    expect(build(["a", "b"])).toEqual(["a", "b"]);
    expect(buildViewInfo(LIST, makeAction(), [LIST], {}, am).props.groupBy).toEqual([]);
});

test("display mode is inDialog for a dialog and the raw target otherwise", async () => {
    const am = makeFakeAm();
    expect(
        buildViewInfo(LIST, makeAction({ target: "new" }), [LIST], {}, am).props
            .display,
    ).toEqual({ mode: "inDialog" });
    expect(
        buildViewInfo(LIST, makeAction({ target: "fullscreen" }), [LIST], {}, am).props
            .display,
    ).toEqual({ mode: "fullscreen" });
});

test("action menus are suppressed for dialogs and for res.config.settings", async () => {
    const am = makeFakeAm();
    const load = (action) =>
        buildViewInfo(LIST, action, [LIST], {}, am).props.loadActionMenus;
    expect(load(makeAction())).toBe(true);
    expect(load(makeAction({ target: "new" }))).toBe(false);
    expect(load(makeAction({ res_model: "res.config.settings" }))).toBe(false);
});

test("ir.filters are loaded only when the action declares a search view", async () => {
    const am = makeFakeAm();
    expect(buildViewInfo(LIST, makeAction(), [LIST], {}, am).props.loadIrFilters).toBe(
        true,
    );
    const noSearch = makeAction({ views: [[false, "list"]] });
    expect(buildViewInfo(LIST, noSearch, [LIST], {}, am).props.loadIrFilters).toBe(
        false,
    );
});

test("help is renamed to noContentHelp; the other special keys keep their names", async () => {
    const action = makeAction({
        help: "<p>nothing here</p>",
        limit: 40,
        count: 5,
        useSampleModel: true,
    });
    const { props } = buildViewInfo(LIST, action, [LIST], {}, makeFakeAm());
    expect(props.noContentHelp).toBe("<p>nothing here</p>");
    expect(props.help).toBe(undefined);
    expect(props.limit).toBe(40);
    expect(props.count).toBe(5);
    expect(props.useSampleModel).toBe(true);
});

test("special keys absent from the action are not invented", async () => {
    const { props } = buildViewInfo(LIST, makeAction(), [LIST], {}, makeFakeAm());
    expect("limit" in props).toBe(false);
    expect("noContentHelp" in props).toBe(false);
});

test("search_disable_custom_filters turns off the favorite", async () => {
    const action = makeAction({ context: { search_disable_custom_filters: true } });
    const { props } = buildViewInfo(LIST, action, [LIST], {}, makeFakeAm());
    expect(props.activateFavorite).toBe(false);
});

test("resId falls back from props to action.res_id to false", async () => {
    const am = makeFakeAm();
    expect(
        buildViewInfo(LIST, makeAction(), [LIST], { resId: 3 }, am).props.resId,
    ).toBe(3);
    expect(
        buildViewInfo(LIST, makeAction({ res_id: 8 }), [LIST], {}, am).props.resId,
    ).toBe(8);
    expect(buildViewInfo(LIST, makeAction(), [LIST], {}, am).props.resId).toBe(false);
});

test("noBreadcrumbs defaults to 'is a dialog' but an explicit flag wins", async () => {
    const am = makeFakeAm();
    const nb = (action) =>
        buildViewInfo(LIST, action, [LIST], {}, am).props.noBreadcrumbs;
    expect(nb(makeAction())).toBe(false);
    expect(nb(makeAction({ target: "new" }))).toBe(true);
    expect(nb(makeAction({ target: "new", _noBreadcrumbs: false }))).toBe(false);
    expect(nb(makeAction({ _noBreadcrumbs: true }))).toBe(true);
});

test("a form opened in a dialog is editable and closes itself on a closable save", async () => {
    const am = makeFakeAm();
    const { props } = buildViewInfo(
        FORM,
        makeAction({ target: "new" }),
        [FORM],
        {},
        am,
    );
    expect(props.readonly).toBe(false);

    props.onSave({}, { closable: true });
    expect(am.__calls.doAction[0].action).toEqual({
        type: "ir.actions.act_window_close",
    });

    props.onSave({}, { closable: false });
    expect(am.__calls.doAction).toHaveLength(1);
});

test("a caller-supplied onSave is not overwritten", async () => {
    const am = makeFakeAm();
    const onSave = () => {};
    const { props } = buildViewInfo(
        FORM,
        makeAction({ target: "new" }),
        [FORM],
        { onSave },
        am,
    );
    expect(props.onSave).toBe(onSave);
});

test("selecting a record switches to the form view when the action has one", async () => {
    const am = makeFakeAm({ _getView: () => FORM });
    const { props } = buildViewInfo(LIST, makeAction(), [LIST, FORM], {}, am);

    props.selectRecord(5, { activeIds: [5, 6], readonly: true, newWindow: true });

    expect(am.__calls.switchView).toHaveLength(1);
    expect(am.__calls.switchView[0].type).toBe("form");
    expect(am.__calls.switchView[0].props).toEqual({
        readonly: true,
        resId: 5,
        resIds: [5, 6],
    });
    expect(am.__calls.switchView[0].options).toEqual({ newWindow: true });
});

test("without a form view, selecting an existing record does nothing", async () => {
    const am = makeFakeAm({ _getView: () => null });
    const { props } = buildViewInfo(LIST, makeAction(), [LIST], {}, am);

    props.selectRecord(5, {});

    expect(am.__calls.switchView).toEqual([]);
    expect(am.__calls.doAction).toEqual([]);
});

test("without a form view, force or a new record dispatches a standalone form action", async () => {
    const am = makeFakeAm({ _getView: () => null });
    const { props } = buildViewInfo(LIST, makeAction(), [LIST], {}, am);

    props.selectRecord(5, { force: true });
    props.createRecord();

    expect(am.__calls.doAction).toHaveLength(2);
    expect(am.__calls.doAction[0].action).toEqual({
        type: "ir.actions.act_window",
        res_model: "partner",
        views: [[false, "form"]],
    });
    expect(am.__calls.doAction[1].options.props.resId).toBe(false);
});

test("a dialog action never navigates on record selection", async () => {
    const am = makeFakeAm({ _getView: () => FORM });
    const { props } = buildViewInfo(
        LIST,
        makeAction({ target: "new" }),
        [LIST],
        {},
        am,
    );

    props.selectRecord(5, { force: true });
    props.createRecord();

    expect(am.__calls.switchView).toEqual([]);
    expect(am.__calls.doAction).toEqual([]);
});

test("embedded actions are suppressed on a form view", async () => {
    const am = makeFakeAm();
    const action = makeAction({
        embedded_action_ids: [{ id: 1 }],
        context: { parent_action_id: 9, current_embedded_action_id: 3 },
    });
    const { config } = buildViewInfo(FORM, action, [FORM], {}, am);
    expect(config.embeddedActions).toEqual([]);
    expect(config.parentActionId).toBe(false);
    expect(config.currentEmbeddedActionId).toBe(3);
});

test("a multi-record view prefers the parent's embedded actions over its own", async () => {
    const am = makeFakeAm();
    const parents = [{ id: 2 }];
    const action = makeAction({
        embedded_action_ids: [{ id: 1 }],
        context: { parent_action_embedded_actions: parents, parent_action_id: 9 },
    });
    const { config } = buildViewInfo(LIST, action, [LIST], {}, am);
    expect(config.embeddedActions).toBe(parents);
    expect(config.parentActionId).toBe(9);
});

test("the search view is skipped and the rest are described from session.view_info", async () => {
    const views = buildActionViews(makeAction());
    expect(views.map((v) => v.type)).toEqual(["list", "form"]);
    for (const view of views) {
        expect(typeof view.multiRecord).toBe("boolean");
        expect(view.display_name).not.toBe(undefined);
    }
});
