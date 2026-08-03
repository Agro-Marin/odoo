// @ts-check

import { expect, test } from "@odoo/hoot";
import { KanbanCompiler } from "@web/views/kanban/kanban_compiler";
import { resetViewCompilerCache, useViewCompiler } from "@web/views/view_compiler";

function compileTemplate(/** @type {string} */ arch) {
    const parser = new DOMParser();
    const xml = parser.parseFromString(arch, "text/xml");
    const compiler = new KanbanCompiler({ kanban: xml.documentElement });
    return compiler.compile("kanban");
}

test("literal ${...} in a field attribute is escaped, not interpolated", async () => {
    const arch = `
        <kanban>
            <templates>
                <t t-name="card">
                    <field name="foo" widget="char" placeholder="Cost \${__comp__.hacked}"/>
                </t>
            </templates>
        </kanban>`;
    const compiled = compileTemplate(arch).outerHTML;
    expect(compiled).toInclude("\\${__comp__.hacked}");
    expect(compiled).not.toInclude("`Cost ${__comp__.hacked}`");
});

test("bootstrap dropdowns with kanban_ignore_dropdown class should be left as is", async () => {
    const arch = `
        <kanban>
            <templates>
                <t t-name="card">
                    <button name="dropdown" class="kanban_ignore_dropdown" type="button" data-bs-toggle="dropdown">Boostrap dropdown</button>
                    <div class="dropdown-menu kanban_ignore_dropdown" role="menu">
                        <span>Dropdown content</span>
                    </div>
                </t>
            </templates>
        </kanban>`;
    const expected = `
        <t t-translation="off">
            <kanban>
                <templates>
                    <t t-name="card">
                        <button name="dropdown" class="kanban_ignore_dropdown" type="button" data-bs-toggle="dropdown">Boostrap dropdown</button>
                        <div class="dropdown-menu kanban_ignore_dropdown" role="menu">
                            <span>Dropdown content</span>
                        </div>
                    </t>
                </templates>
            </kanban>
        </t>`;
    expect(compileTemplate(arch)).toHaveOuterHTML(expected);
});

test("data-self-handled is honoured like data-bs-toggle and left as is", async () => {
    const arch = `
        <kanban>
            <templates>
                <t t-name="card">
                    <button name="menu" type="button" data-self-handled="1">Own click</button>
                </t>
            </templates>
        </kanban>`;
    const expected = `
        <t t-translation="off">
            <kanban>
                <templates>
                    <t t-name="card">
                        <button name="menu" type="button" data-self-handled="1">Own click</button>
                    </t>
                </templates>
            </kanban>
        </t>`;
    expect(compileTemplate(arch)).toHaveOuterHTML(expected);
});

test("a t-call is compiled against the sibling set it arrived with", async () => {
    // The compiled `t-call` differs depending on whether the called name is a
    // sibling template, so two views whose card arch is byte-identical must not
    // share a compiled template.
    resetViewCompilerCache();
    const card = `<div class="probe-card"><t t-call="sub"/></div>`;
    const parse = (/** @type {string} */ s) =>
        new DOMParser().parseFromString(s, "text/xml").documentElement;

    const withSibling = { card: parse(card), sub: parse(`<span>S</span>`) };
    const withoutSibling = { card: parse(card) };

    const keysWith = useViewCompiler(KanbanCompiler, withSibling);
    const keysWithout = useViewCompiler(KanbanCompiler, withoutSibling);

    expect(keysWith.card).not.toBe(keysWithout.card);
    expect(new KanbanCompiler(withSibling).compile("card").outerHTML).toInclude(
        "__comp__.templates",
    );
    expect(new KanbanCompiler(withoutSibling).compile("card").outerHTML).not.toInclude(
        "__comp__.templates",
    );
});
