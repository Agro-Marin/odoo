// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    click,
    edit,
    manuallyDispatchProgrammaticEvent,
    queryAll,
    queryAllProperties,
    queryFirst,
    setInputFiles,
    waitFor,
} from "@odoo/hoot-dom";
import { animationFrame, mockDate, runAllTimers } from "@odoo/hoot-mock";
import {
    clickFieldDropdownItem,
    clickSave,
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    pagerNext,
    webModels,
} from "@web/../tests/web_test_helpers";
import { luxon } from "@web/core/l10n/luxon";
import { getOrigin } from "@web/core/utils/urls";

const { DateTime } = luxon;

const MY_IMAGE =
    "iVBORw0KGgoAAAANSUhEUgAAAAUAAAAFCAYAAACNbyblAAAAHElEQVQI12P4//8/w38GIAXDIBKE0DHxgljNBAAO9TXL0Y4OHwAAAABJRU5ErkJggg==";
const PRODUCT_IMAGE =
    "R0lGODlhDAAMAKIFAF5LAP/zxAAAANyuAP/gaP///wAAAAAAACH5BAEAAAUALAAAAAAMAAwAAAMlWLPcGjDKFYi9lxKBOaGcF35DhWHamZUW0K4mAbiwWtuf0uxFAgA7";

function getUnique(target) {
    const src = target.dataset.src;
    return new URL(src).searchParams.get("unique");
}

async function setFiles(files, name = "document") {
    await click("input[type=file]", { visible: false });
    await setInputFiles(files);
    await waitFor(`div[name=${name}] img[data-src^="data:image/"]`, { timeout: 1000 });
}

class Partner extends models.Model {
    name = fields.Char();
    timmy = fields.Many2many({ relation: "partner.type" });
    foo = fields.Char();
    document = fields.Binary();

    _records = [
        { id: 1, name: "first record", timmy: [], document: "coucou==" },
        { id: 2, name: "second record", timmy: [] },
        { id: 4, name: "aaa" },
    ];
}

class PartnerType extends models.Model {
    _name = "partner.type";

    name = fields.Char();
    color = fields.Integer();

    _records = [
        { id: 12, name: "gold", color: 2 },
        { id: 14, name: "silver", color: 5 },
    ];
}

defineModels([Partner, PartnerType]);

test("ImageField is correctly rendered", async () => {
    expect.assertions(10);

    Partner._records[0].write_date = "2017-02-08 10:00:00";
    Partner._records[0].document = MY_IMAGE;

    onRpc("web_read", ({ kwargs }) => {
        expect(kwargs.specification).toEqual(
            {
                display_name: {},
                document: {},
                write_date: {},
            },
            {
                message:
                    "The fields document, name and write_date should be present when reading an image",
            },
        );
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'size': [90, 90]}"/>
            </form>
        `,
    });

    expect(".o_field_widget[name='document']").toHaveClass("o_field_image", {
        message: "the widget should have the correct class",
    });
    expect(".o_field_widget[name='document'] img").toHaveCount(1, {
        message: "the widget should contain an image",
    });
    expect('div[name="document"] img').toHaveAttribute(
        "data-src",
        `data:image/png;base64,${MY_IMAGE}`,
        { message: "the image should have the correct src" },
    );
    expect(".o_field_widget[name='document'] img").toHaveClass("img-fluid", {
        message: "the image should have the correct class",
    });
    expect(".o_field_widget[name='document'] img").toHaveAttribute("width", "90", {
        message: "the image should correctly set its attributes",
    });
    expect(".o_field_widget[name='document'] img").toHaveStyle(
        {
            maxWidth: "90px",
            width: "90px",
            height: "90px",
        },
        {
            message: "the image should correctly set its attributes",
        },
    );
    expect(".o_field_image .o_select_file_button").toHaveCount(1, {
        message: "the image can be edited",
    });
    expect(".o_field_image .o_clear_file_button").toHaveCount(1, {
        message: "the image can be deleted",
    });
    expect("input.o_input_file").toHaveAttribute(
        "accept",
        "image/*,dummy/allowAndroidCamera",
        {
            message:
                'the default value for the attribute "accept" on the "image" widget must be "image/*"',
        },
    );
});

test("ImageField with img_class option", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="document" widget="image" options="{'img_class': 'my_custom_class'}"/>
            </form>`,
    });

    expect(".o_field_image img").toHaveClass("my_custom_class");
});

test("ImageField with alt attribute", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="document" widget="image" alt="something"/>
            </form>`,
    });

    expect(".o_field_widget[name='document'] img").toHaveAttribute("alt", "something", {
        message: "the image should correctly set its alt attribute",
    });
});

test("ImageField on a many2one", async () => {
    Partner._fields.parent_id = fields.Many2one({ relation: "partner" });
    Partner._records[1].parent_id = 1;

    mockDate("2017-02-06 10:00:00");

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 2,
        arch: /* xml */ `
            <form>
                <field name="parent_id" widget="image" options="{'preview_image': 'document'}"/>
            </form>`,
    });

    expect(".o_field_widget[name=parent_id] img").toHaveCount(1);
    expect('div[name="parent_id"] img').toHaveAttribute(
        "data-src",
        `${getOrigin()}/web/image/partner/1/document?unique=1486375200000`,
    );
    expect(".o_field_widget[name='parent_id'] img").toHaveAttribute(
        "alt",
        "first record",
    );
});

// desktop-only: changes the m2o value through the inline autocomplete/kanban
// selector; mobile selects m2o values via a dialog with different DOM.
test.tags("desktop");
test("many2one image url is busted with a fresh timestamp when its value changes", async () => {
    // A many2one image URL targets the RELATED record (partner/<value.id>), so
    // the parent record's write_date is not a valid cache key for it: when the
    // linked record changes (or its image is edited via the m2o dialog, which
    // only refreshes display_name) the parent's write_date has not moved and
    // the browser would serve a stale image. The field must bust with `now()`.
    Partner._fields.parent_id = fields.Many2one({ relation: "partner" });
    Partner._records[1].parent_id = 1;
    Partner._records[1].write_date = "2017-02-01 10:00:00"; // 1485943200000

    mockDate("2017-02-06 10:00:00");

    // parent_id is shown twice: once as the plain m2o selector (to change the
    // value) and once as the image widget (the field under test).
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 2,
        arch: /* xml */ `
            <form>
                <field name="parent_id"/>
                <field name="parent_id" widget="image" options="{'preview_image': 'document'}"/>
            </form>`,
    });

    // Initial render: parent's write_date is fine because the value hasn't
    // changed yet.
    expect('.o_field_image[name="parent_id"] img').toHaveAttribute(
        "data-src",
        `${getOrigin()}/web/image/partner/1/document?unique=1485943200000`,
    );

    // Point the m2o at a different record: the value changes but the parent's
    // write_date does not. The cache key must jump to a fresh `now()`.
    mockDate("2017-02-09 10:00:00");
    await contains(".o_field_many2one[name='parent_id'] input").edit("aaa", {
        confirm: false,
    });
    await runAllTimers();
    await clickFieldDropdownItem("parent_id", "aaa");
    await animationFrame();

    const img = queryFirst('.o_field_image[name="parent_id"] img');
    expect(img.getAttribute("data-src")).toMatch(/\/web\/image\/partner\/4\/document/);
    const unique = Number(getUnique(img));
    expect(
        DateTime.fromMillis(unique).hasSame(DateTime.fromISO("2017-02-09"), "days"),
    ).toBe(true);
});

test("url should not use the record last updated date when the field is related", async () => {
    Partner._fields.related = fields.Binary({ related: "parent_id.document" });
    Partner._fields.parent_id = fields.Many2one({ relation: "partner" });
    Partner._records[1].parent_id = 1;
    Partner._records[0].write_date = "2017-02-04 10:00:00";
    Partner._records[0].document = "3 kb";

    mockDate("2017-02-06 10:00:00");

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 2,
        arch: `
            <form>
                <field name="foo"/>
                <field name="related" widget="image" readonly="0"/>
            </form>`,
    });

    const initialUnique = Number(getUnique(queryFirst('div[name="related"] img')));
    expect(
        DateTime.fromMillis(initialUnique).hasSame(
            DateTime.fromISO("2017-02-06"),
            "days",
        ),
    ).toBe(true);

    await click(".o_field_widget[name='foo'] input");
    await edit("grrr");
    await animationFrame();

    expect(Number(getUnique(queryFirst('div[name="related"] img')))).toBe(
        initialUnique,
    );

    mockDate("2017-02-09 10:00:00");

    await click("input[type=file]", { visible: false });
    await setFiles(
        new File(
            [Uint8Array.from([...atob(MY_IMAGE)].map((c) => c.charCodeAt(0)))],
            "fake_file.png",
            { type: "image/png" },
        ),
        "related",
    );

    expect("div[name=related] img").toHaveAttribute(
        "data-src",
        `data:image/png;base64,${MY_IMAGE}`,
    );

    await clickSave();

    const unique = Number(getUnique(queryFirst('div[name="related"] img')));
    expect(
        DateTime.fromMillis(unique).hasSame(DateTime.fromISO("2017-02-09"), "days"),
    ).toBe(true);
});

test("url should use the record last updated date when the field is related on the same model", async () => {
    Partner._fields.related = fields.Binary({ related: "document" });
    Partner._records[0].write_date = "2017-02-04 10:00:00"; // 1486202400000
    Partner._records[0].document = "3 kb";

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="related" widget="image"/>
            </form>`,
    });
    expect('div[name="related"] img').toHaveAttribute(
        "data-src",
        `${getOrigin()}/web/image/partner/1/related?unique=1486202400000`,
    );
});

test("ImageField is correctly replaced when given an incorrect value", async () => {
    Partner._records[0].document = "incorrect_base64_value";

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'size': [90, 90]}"/>
            </form>
        `,
    });

    expect(`div[name="document"] img`).toHaveAttribute(
        "data-src",
        "data:image/png;base64,incorrect_base64_value",
        {
            message: "the image has the invalid src by default",
        },
    );

    // GET requests can't occur in tests, so manually fire an error on the
    // img element to verify data-src falls back to the placeholder.
    manuallyDispatchProgrammaticEvent(queryFirst('div[name="document"] img'), "error");
    await animationFrame();

    expect('.o_field_widget[name="document"]').toHaveClass("o_field_image", {
        message: "the widget should have the correct class",
    });
    expect(".o_field_widget[name='document'] img").toHaveCount(1, {
        message: "the widget should contain an image",
    });
    expect('div[name="document"] img').toHaveAttribute(
        "data-src",
        "/web/static/img/placeholder.png",
        { message: "the image should have the correct src" },
    );
    expect(".o_field_widget[name='document'] img").toHaveClass("img-fluid", {
        message: "the image should have the correct class",
    });
    expect(".o_field_widget[name='document'] img").toHaveAttribute("width", "90", {
        message: "the image should correctly set its attributes",
    });
    expect(".o_field_widget[name='document'] img").toHaveStyle("maxWidth: 90px", {
        message: "the image should correctly set its attributes",
    });

    expect(".o_field_image .o_select_file_button").toHaveCount(1, {
        message: "the image can be edited",
    });
    expect(".o_field_image .o_clear_file_button").toHaveCount(0, {
        message: "the image cannot be deleted as it has not been uploaded",
    });
});

test("ImageField preview is updated when an image is uploaded", async () => {
    const imageFile = new File(
        [Uint8Array.from([...atob(MY_IMAGE)].map((c) => c.charCodeAt(0)))],
        "fake_file.png",
        { type: "image/png" },
    );
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'size': [90, 90]}"/>
            </form>
        `,
    });

    expect('div[name="document"] img').toHaveAttribute(
        "data-src",
        "data:image/png;base64,coucou==",
        { message: "the image should have the initial src" },
    );
    // Whitebox: swap the event target before the field handles it, since
    // it reads files from event.target rather than the input element.
    await click(".o_select_file_button");
    await setInputFiles(imageFile);
    // It can take some time to encode the data as a base64 url
    await waitFor(
        `div[name=document] img[data-src="data:image/png;base64,${MY_IMAGE}"]`,
    );
});

test("clicking save manually after uploading new image should change the unique of the image src", async () => {
    Partner._onChanges.foo = () => {};

    const rec = Partner._records.find((rec) => rec.id === 1);
    rec.document = "3 kb";
    rec.write_date = "2022-08-05 08:37:00"; // 1659688620000

    // 1659692220000, 1659695820000
    const lastUpdates = ["2022-08-05 09:37:00", "2022-08-05 10:37:00"];
    let index = 0;

    onRpc("web_save", ({ args }) => {
        args[1].write_date = lastUpdates[index];
        args[1].document = "4 kb";
        index++;
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="foo"/>
                <field name="document" widget="image" />
            </form>
        `,
    });
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659688620000");

    await click("input[type=file]", { visible: false });
    await setFiles(
        new File(
            [Uint8Array.from([...atob(MY_IMAGE)].map((c) => c.charCodeAt(0)))],
            "fake_file.png",
            { type: "image/png" },
        ),
    );
    expect("div[name=document] img").toHaveAttribute(
        "data-src",
        `data:image/png;base64,${MY_IMAGE}`,
    );

    await click(".o_field_widget[name='foo'] input");
    await edit("grrr");
    await animationFrame();
    expect("div[name=document] img").toHaveAttribute(
        "data-src",
        `data:image/png;base64,${MY_IMAGE}`,
    );

    await clickSave();
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659692220000");

    // Change the image again. After clicking save, it should have the correct new url.
    await click("input[type=file]", { visible: false });
    await setFiles(
        new File(
            [Uint8Array.from([...atob(PRODUCT_IMAGE)].map((c) => c.charCodeAt(0)))],
            "fake_file2.gif",
            { type: "image/gif" },
        ),
    );
    expect("div[name=document] img").toHaveAttribute(
        "data-src",
        `data:image/gif;base64,${PRODUCT_IMAGE}`,
    );

    await clickSave();
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659695820000");
});

test("save record with image field modified by onchange", async () => {
    Partner._onChanges.foo = (data) => {
        data.document = MY_IMAGE;
    };
    const rec = Partner._records.find((rec) => rec.id === 1);
    rec.document = "3 kb";
    rec.write_date = "2022-08-05 08:37:00"; // 1659688620000

    // 1659692220000
    const lastUpdates = ["2022-08-05 09:37:00"];
    let index = 0;

    onRpc("web_save", ({ args }) => {
        args[1].write_date = lastUpdates[index];
        args[1].document = "3 kb";
        index++;
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="foo"/>
                <field name="document" widget="image" />
            </form>
        `,
    });
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659688620000");
    await click("[name='foo'] input");
    await edit("grrr", { confirm: "enter" });
    await animationFrame();
    expect("div[name=document] img").toHaveAttribute(
        "data-src",
        `data:image/png;base64,${MY_IMAGE}`,
    );

    await clickSave();
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659692220000");
});

test("ImageField: option accepted_file_extensions", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'accepted_file_extensions': '.png,.jpeg'}" />
            </form>
        `,
    });
    // The view must be in edit mode
    expect("input.o_input_file").toHaveAttribute(
        "accept",
        ".png,.jpeg,dummy/allowAndroidCamera",
        {
            message: "the input should have the correct ``accept`` attribute",
        },
    );
});

test("ImageField: set 0 width/height in the size option", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'size': [0, 0]}" />
                <field name="document" widget="image" options="{'size': [0, 50]}" />
                <field name="document" widget="image" options="{'size': [50, 0]}" />
            </form>
        `,
    });

    const imgs = queryAll(".o_field_widget img");

    expect([imgs[0].attributes.width, imgs[0].attributes.height]).toEqual(
        [undefined, undefined],
        {
            message: "if both size are set to 0, both attributes are undefined",
        },
    );

    expect([imgs[1].attributes.width, imgs[1].attributes.height.value]).toEqual(
        [undefined, "50"],
        {
            message:
                "if only the width is set to 0, the width attribute is not set on the img",
        },
    );
    expect([
        imgs[1].style.width,
        imgs[1].style.maxWidth,
        imgs[1].style.height,
        imgs[1].style.maxHeight,
    ]).toEqual(["auto", "100%", "", "50px"], {
        message: "the image should correctly set its attributes",
    });

    expect([imgs[2].attributes.width.value, imgs[2].attributes.height]).toEqual(
        ["50", undefined],
        {
            message:
                "if only the height is set to 0, the height attribute is not set on the img",
        },
    );
    expect([
        imgs[2].style.width,
        imgs[2].style.maxWidth,
        imgs[2].style.height,
        imgs[2].style.maxHeight,
    ]).toEqual(["", "50px", "auto", "100%"], {
        message: "the image should correctly set its attributes",
    });
});

test("ImageField: zoom and zoom_delay options (readonly)", async () => {
    Partner._records[0].document = MY_IMAGE;

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'zoom': true, 'zoom_delay': 600}" readonly="1" />
            </form>
        `,
    });
    // data-tooltip attribute is used by the tooltip service
    expect(".o_field_image img").toHaveAttribute(
        "data-tooltip-info",
        `{"url":"data:image/png;base64,${MY_IMAGE}"}`,
        { message: "shows a tooltip on hover" },
    );
    expect(".o_field_image img").toHaveAttribute("data-tooltip-delay", "600", {
        message: "tooltip has the right delay",
    });
});

test("ImageField: zoom and zoom_delay options (edit)", async () => {
    Partner._records[0].document = "3 kb";
    Partner._records[0].write_date = "2022-08-05 08:37:00";

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'zoom': true, 'zoom_delay': 600}" />
            </form>
        `,
    });

    expect(".o_field_image img").toHaveAttribute(
        "data-tooltip-info",
        `{"url":"${getOrigin()}/web/image/partner/1/document?unique=1659688620000"}`,
        { message: "tooltip show the full image from the field value" },
    );
    expect(".o_field_image img").toHaveAttribute("data-tooltip-delay", "600", {
        message: "tooltip has the right delay",
    });
});

test("ImageField displays the right images with zoom and preview_image options (readonly)", async () => {
    Partner._records[0].document = "3 kb";
    Partner._records[0].write_date = "2022-08-05 08:37:00";

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'zoom': true, 'preview_image': 'document_preview', 'zoom_delay': 600}" readonly="1" />
            </form>
        `,
    });
    expect(".o_field_image img").toHaveAttribute(
        "data-tooltip-info",
        `{"url":"${getOrigin()}/web/image/partner/1/document?unique=1659688620000"}`,
        { message: "tooltip show the full image from the field value" },
    );
    expect(".o_field_image img").toHaveAttribute("data-tooltip-delay", "600", {
        message: "tooltip has the right delay",
    });
});

test("ImageField in subviews is loaded correctly", async () => {
    Partner._records[0].write_date = "2017-02-08 10:00:00";
    Partner._records[0].document = MY_IMAGE;
    PartnerType._fields.image = fields.Binary({});
    PartnerType._records[0].image = PRODUCT_IMAGE;
    Partner._records[0].timmy = [12];

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'size': [90, 90]}" />
                <field name="timmy" widget="many2many" mode="kanban">
                    <kanban>
                        <templates>
                            <t t-name="card">
                                <field name="name" />
                            </t>
                        </templates>
                    </kanban>
                    <form>
                        <field name="image" widget="image" />
                    </form>
                </field>
            </form>
        `,
    });

    expect(`img[data-src="data:image/png;base64,${MY_IMAGE}"]`).toHaveCount(1);
    expect(
        ".o_kanban_record:not(.o_kanban_ghost):not(.o-kanban-button-new)",
    ).toHaveCount(1);

    // Actual flow: click on an element of the m2m to get its form view
    await click(".o_kanban_record:not(.o_kanban_ghost):not(.o-kanban-button-new)");
    await animationFrame();
    expect(".modal").toHaveCount(1, { message: "The modal should have opened" });

    expect(`img[data-src="data:image/gif;base64,${PRODUCT_IMAGE}"]`).toHaveCount(1);
});

test("ImageField in x2many list is loaded correctly", async () => {
    PartnerType._fields.image = fields.Binary({});
    PartnerType._records[0].image = PRODUCT_IMAGE;
    Partner._records[0].timmy = [12];

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="timmy" widget="many2many">
                    <list>
                        <field name="image" widget="image" />
                    </list>
                </field>
            </form>
        `,
    });

    expect("tr.o_data_row").toHaveCount(1, {
        message: "There should be one record in the many2many",
    });
    expect(`img[data-src="data:image/gif;base64,${PRODUCT_IMAGE}"]`).toHaveCount(1, {
        message: "The list's image is in the DOM",
    });
});

test("ImageField with required attribute", async () => {
    onRpc("create", () => {
        throw new Error("Should not do a create RPC with unset required image field");
    });
    await mountView({
        type: "form",
        resModel: "partner",
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" required="1" />
            </form>
        `,
    });

    await clickSave();

    expect(".o_form_view .o_form_editable").toHaveCount(1, {
        message: "form view should still be editable",
    });
    expect(".o_field_widget").toHaveClass("o_field_invalid", {
        message: "image field should be displayed as invalid",
    });
});

test("ImageField is reset when changing record", async () => {
    const imageData = Uint8Array.from([...atob(MY_IMAGE)].map((c) => c.charCodeAt(0)));
    await mountView({
        type: "form",
        resModel: "partner",
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" options="{'size': [90, 90]}"/>
            </form>
        `,
    });

    const imageFile = new File([imageData], "fake_file.png", { type: "image/png" });
    expect("img[alt='Binary file']").toHaveAttribute(
        "data-src",
        "/web/static/img/placeholder.png",
        { message: "image field should not be set" },
    );

    await setFiles(imageFile);
    expect("img[alt='Binary file']").toHaveAttribute(
        "data-src",
        `data:image/png;base64,${MY_IMAGE}`,
        {
            message: "image field should be set",
        },
    );

    await clickSave();
    await click(".o_control_panel_main_buttons .o_form_button_create");
    await runAllTimers();
    await animationFrame();
    expect("img[alt='Binary file']").toHaveAttribute(
        "data-src",
        "/web/static/img/placeholder.png",
        { message: "image field should be reset" },
    );

    await setFiles(imageFile);
    expect("img[alt='Binary file']").toHaveAttribute(
        "data-src",
        `data:image/png;base64,${MY_IMAGE}`,
        {
            message: "image field should be set",
        },
    );
});
test("unique in url doesn't change on onchange", async () => {
    Partner._onChanges.foo = () => {};

    const rec = Partner._records.find((rec) => rec.id === 1);
    rec.document = "3 kb";
    rec.write_date = "2022-08-05 08:37:00";

    onRpc(({ method, args }) => {
        expect.step(method);
        if (method === "web_save") {
            args[1].write_date = "2022-08-05 09:37:00"; // 1659692220000
        }
    });
    await mountView({
        resId: 1,
        type: "form",
        resModel: "partner",
        arch: /* xml */ `
            <form>
                <field name="foo" />
                <field name="document" widget="image" required="1" />
            </form>
        `,
    });

    expect.verifySteps(["get_views", "web_read"]);
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659688620000");

    expect.verifySteps([]);
    // same unique as before
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659688620000");

    await click(".o_field_widget[name='foo'] input");
    await edit("grrr", { confirm: "enter" });
    await animationFrame();
    expect.verifySteps(["onchange"]);
    // also same unique
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659688620000");

    await clickSave();
    expect.verifySteps(["web_save"]);

    // saving without touching the image must not bust its URL: the unique
    // key follows the image value, not the record's write_date
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659688620000");
});

test("unique in url change on record change", async () => {
    const rec = Partner._records.find((rec) => rec.id === 1);
    rec.document = "3 kb";
    rec.write_date = "2022-08-05 08:37:00";

    const rec2 = Partner._records.find((rec) => rec.id === 2);
    rec2.document = "3 kb";
    rec2.write_date = "2022-08-05 09:37:00";

    await mountView({
        resIds: [1, 2],
        resId: 1,
        type: "form",
        resModel: "partner",
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" required="1" />
            </form>
        `,
    });

    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659688620000");
    await pagerNext();
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659692220000");
});

test("unique in url does not change on record change if reload option is set to false", async () => {
    const rec = Partner._records.find((rec) => rec.id === 1);
    rec.document = "3 kb";
    rec.write_date = "2022-08-05 08:37:00";

    await mountView({
        resIds: [1, 2],
        resId: 1,
        type: "form",
        resModel: "partner",
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" required="1" options="{'reload': false}" />
                <field name="write_date" readonly="0"/>
            </form>
        `,
    });
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659688620000");
    await contains("div[name='write_date'] > div > button").click();
    await edit("2022-08-05 08:39:00", { confirm: "enter" });
    await animationFrame();
    await clickSave();
    expect(getUnique(queryFirst(".o_field_image img"))).toBe("1659688620000");
});

test("convert image to webp", async () => {
    onRpc("ir.attachment", "create_unique", ({ args }) => {
        // Called twice: once storing webp, once storing jpeg.
        if (!args[0][0].res_id) {
            expect(args[0][0].datas).not.toBe(imageData);
            expect(args[0][0].mimetype).toBe("image/webp");
            return [1];
        }
        // Second call: jpeg.
        expect(args[0][0].datas).not.toBe(imageData);
        expect(args[0][0].mimetype).toBe("image/jpeg");
        return true;
    });

    const imageData = Uint8Array.from([...atob(MY_IMAGE)].map((c) => c.charCodeAt(0)));
    await mountView({
        type: "form",
        resModel: "partner",
        arch: /* xml */ `
            <form>
                <field name="document" widget="image" required="1" options="{'convert_to_webp': True}" />
            </form>
        `,
    });

    const imageFile = new File([imageData], "fake_file.jpeg", { type: "image/jpeg" });
    expect("img[alt='Binary file']").toHaveAttribute(
        "data-src",
        "/web/static/img/placeholder.png",
        { message: "image field should not be set" },
    );
    await setFiles(imageFile);
});

test.tags("desktop");
test("ImageField with width attribute in list", async () => {
    const { ResCompany, ResPartner, ResUsers } = webModels;
    defineModels([ResCompany, ResPartner, ResUsers]);

    await mountView({
        type: "list",
        resModel: "partner",
        arch: /* xml */ `
            <list>
                <field name="document" widget="image" width="30"/>
                <field name="foo"/>
            </list>
        `,
    });

    expect(".o_data_row").toHaveCount(3);
    expect(".o_field_widget[name=document] img").toHaveCount(3);
    expect(
        queryAllProperties(".o_list_table th[data-name=document]", "offsetWidth"),
    ).toEqual([39]);
});
