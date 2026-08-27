// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { AceEditorController } from "@web/components/code_editor/ace_editor_hook";

describe.current.tags("headless");

/**
 * A stand-in for the parts of Ace this controller drives. The point of pulling
 * the controller out of `setup` is that it can be exercised like this: no Owl,
 * no DOM, no ace_lib bundle.
 */
function makeAce() {
    const log = [];
    class Session {
        constructor(value = "") {
            this.value = value;
            this.handlers = [];
            this.options = null;
            this.mode = null;
        }
        getValue() {
            return this.value;
        }
        setValue(value) {
            this.value = value;
            for (const handler of this.handlers) {
                handler();
            }
        }
        on(_event, handler) {
            this.handlers.push(handler);
        }
        setUndoManager() {}
        setOptions(options) {
            this.options = options;
        }
        setMode(mode) {
            this.mode = mode;
        }
        destroy() {
            log.push("session destroyed");
        }
    }
    const editor = {
        session: new Session("initial"),
        cursor: { row: 0, column: 0 },
        renderer: {
            setOptions: () => {},
            $cursorLayer: { element: { style: {} } },
            scrollCursorIntoView: () => log.push("scrolled"),
        },
        selection: {
            moveToPosition: (pos) => log.push(`moved ${pos.row}:${pos.column}`),
        },
        getSession() {
            return this.session;
        },
        setSession(session) {
            this.session = session;
            log.push("session switched");
        },
        getValue() {
            return this.session.getValue();
        },
        getCursorPosition() {
            return this.cursor;
        },
        setOptions: () => {},
        setTheme: (theme) => log.push(`theme ${theme}`),
        on: () => {},
        focus: () => log.push("focused"),
        destroy: () => log.push("editor destroyed"),
    };
    // Restored after the test: leaking this stub hands the real CodeEditor suites
    // a fake Ace, and they fail only when run in the same page as this file.
    patchWithCleanup(window, {
        ace: {
            edit: () => editor,
            EditSession: Session,
            UndoManager: class {},
        },
    });
    return { editor, log };
}

/**
 * @param {Partial<Record<string, any>>} [overrides]
 */
function makeController(overrides = {}) {
    const changes = [];
    const controller = new AceEditorController({
        ref: { el: null },
        getValue: () => "initial",
        getSessionId: () => "a",
        getMode: () => "python",
        getTheme: () => "",
        isReadonly: () => false,
        showLineNumbers: () => true,
        getMaxLines: () => undefined,
        onChange: (value) => changes.push(value),
        ...overrides,
    });
    return { controller, changes };
}

test("a session is created once per id and reused", () => {
    makeAce();
    const { controller } = makeController();
    controller.attach(document.createElement("div"));

    const first = controller.acquireSession("b");
    expect(controller.acquireSession("b")).toBe(first);
    expect(controller.acquireSession("c")).not.toBe(first);
});

test("attach adopts Ace's own session rather than opening a second one", () => {
    const { editor } = makeAce();
    const { controller } = makeController();
    controller.attach(document.createElement("div"));

    expect(controller.sessions["a"]).toBe(editor.session);
});

test("a programmatic value sync is not reported back as an edit", () => {
    makeAce();
    const { controller, changes } = makeController();
    controller.attach(document.createElement("div"));
    expect(changes).toEqual([]);

    // Ace fires `change` for setValue too. Reporting that to the caller is how a
    // value round-trips into an edit loop.
    controller.syncValue("a", "from the outside");
    expect(changes).toEqual([]);
    expect(controller.sessions["a"].getValue()).toBe("from the outside");

    // A change Ace did not originate still reaches the caller.
    controller.sessions["a"].handlers.at(-1)();
    expect(changes).toEqual(["from the outside"]);
});

test("syncing a value that already matches touches nothing", () => {
    makeAce();
    const { controller } = makeController();
    controller.attach(document.createElement("div"));
    const session = controller.sessions["a"];
    session.value = "same";

    controller.syncValue("a", "same");
    expect(session.getValue()).toBe("same");
    expect(controller.ignoreAceChange).toBe(false);
});

test("detach destroys the editor and every session it opened", () => {
    const { log } = makeAce();
    const { controller } = makeController();
    const teardown = controller.attach(document.createElement("div"));
    controller.acquireSession("b");

    teardown();
    expect(controller.editor).toBe(null);
    expect(controller.sessions).toEqual({});
    expect(log.filter((entry) => entry === "session destroyed")).toHaveLength(2);
    expect(log).toInclude("editor destroyed");
});

test("options and theme are inert before an editor exists", () => {
    makeAce();
    const { controller } = makeController();
    // Owl runs the option effects in registration order after the attach one, but
    // nothing guarantees an element was there for it.
    expect(() => controller.applyTheme("monokai")).not.toThrow();
    expect(() => controller.applyOptions(true, false, 10)).not.toThrow();
    expect(() => controller.showSession("a", "xml")).not.toThrow();
    expect(() => controller.syncValue("a", "x")).not.toThrow();
    expect(() => controller.placeCursor({ row: 1, column: 2 })).not.toThrow();
});
