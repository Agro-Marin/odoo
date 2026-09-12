/** @odoo-module native */
import { Component, onMounted, reactive, useRef, xml } from "@odoo/owl";
import { toCanvas } from "@point_of_sale/app/utils/html-to-image";
import { waitImages } from "@point_of_sale/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Mutex } from "@web/core/utils/concurrency";

const renderMutex = new Mutex();
const log = makeLogger("pos.render");
class ComponentRenderer extends Component {
    static props = ["comp", "onMounted"];
    static template = xml`
        <div t-ref="ref">
            <t t-component="props.comp.component" t-props="props.comp.props"/>
        </div>
    `;
    setup() {
        this.ref = useRef("ref");
        onMounted(() => {
            this.props.onMounted(this.ref?.el?.firstElementChild);
        });
    }
}

export class RenderContainer extends Component {
    static props = ["comp", "onRendered"];
    static components = { ComponentRenderer };
    static template = xml`
        <div class="render-container-parent" style="left: -1000px; position: fixed;">
            <t t-if="props.comp.component">
                <ComponentRenderer comp="props.comp" onMounted="props.onRendered" />
            </t>
            <div class="render-container" />
        </div>`;
}
export const renderService = {
    dependencies: [],
    start() {
        const toBeRenderedComponentData = reactive({});
        let elem, resolver;
        registry.category("main_components").add("RenderContainer", {
            Component: RenderContainer,
            props: {
                comp: toBeRenderedComponentData,
                onRendered: (el) => {
                    elem = el;
                    resolver?.();
                    toBeRenderedComponentData.component = null;
                },
            },
        });
        const toHtml = (component, props) =>
            renderMutex.exec(async () => {
                const endRender = log.perf(`toHtml ${component?.name}`);
                Object.assign(toBeRenderedComponentData, { component, props });
                let timer;
                try {
                    await new Promise((resolve, reject) => {
                        resolver = resolve;
                        timer = setTimeout(
                            () =>
                                reject(
                                    new Error(
                                        `Component '${component?.name}' could not be rendered to HTML`,
                                    ),
                                ),
                            10000,
                        );
                    });
                } finally {
                    clearTimeout(timer);
                    toBeRenderedComponentData.component = null;
                    endRender({ tag: elem?.tagName });
                }
                return elem;
            });
        const toCanvas = async (component, props, options) =>
            htmlToCanvas(await toHtml(component, props), options);
        const toJpeg = async (component, props, options) => {
            const canvas = await toCanvas(component, props, options);
            const endEncode = log.perf(`toJpeg ${component?.name}`);
            const jpeg = canvas
                .toDataURL("image/jpeg")
                .replace("data:image/jpeg;base64,", "");
            endEncode({
                width: canvas.width,
                height: canvas.height,
                bytes: jpeg.length,
            });
            return jpeg;
        };
        const whenMounted = async ({ el, container, callback }) => {
            container ||= document.querySelector(".render-container");
            container.textContent = "";
            return await applyWhenMounted({ el, container, callback });
        };
        return { toHtml, toCanvas, toJpeg, whenMounted };
    },
};
registry.category("services").add("renderer", renderService);

const applyWhenMounted = async ({ el, container, callback }) => {
    const elClone = el.cloneNode(true);
    const sameClassElements = container.querySelectorAll(
        `.${[...el.classList].join(".")}`,
    );
    sameClassElements.forEach((element) => {
        element.remove();
    });
    container.appendChild(elClone);
    const res = await callback(elClone);
    return res;
};

const sanitizeNodeText = (element) => {
    if (element.nodeType === Node.TEXT_NODE) {
        element.textContent = element.textContent.replace(
            // eslint-disable-next-line no-control-regex -- deliberately strip control chars before rendering
            /[\x00-\x08\x0B\x0C\x0E-\x1F]/g,
            "",
        );
        return;
    }
    for (const child of element.childNodes) {
        sanitizeNodeText(child);
    }
};

export const htmlToCanvas = async (el, options) => {
    if (options.addClass) {
        el.classList.add(...options.addClass.split(" "));
    }
    sanitizeNodeText(el);
    const endCanvas = log.perf("htmlToCanvas");
    return await renderMutex.exec(() =>
        applyWhenMounted({
            el,
            container: document.querySelector(".render-container"),
            callback: async (el) => {
                await waitImages(el);
                const canvas = await toCanvas(el, {
                    backgroundColor: "#ffffff",
                    height: Math.ceil(el.clientHeight),
                    width: Math.ceil(el.clientWidth),
                    pixelRatio: 1,
                    includeQueryParams: true,
                });
                endCanvas({ width: canvas.width, height: canvas.height });
                return canvas;
            },
        }),
    );
};
