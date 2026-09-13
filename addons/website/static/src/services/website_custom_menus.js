/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { EditMenuDialog } from "@website/components/dialog/edit_menu";
import { PagePropertiesDialog } from "@website/components/dialog/page_properties";
import { OptimizeSEODialog } from "@website/components/dialog/seo";

const log = makeLogger("website.service.custom_menus");

export const websiteCustomMenus = {
    dependencies: ["website", "orm", "dialog", "ui"],
    start(env, { website, orm, dialog, ui }) {
        const services = { website, orm, dialog, ui };
        return {
            get(xmlId) {
                return registry.category("website_custom_menus").get(xmlId, null);
            },
            async open(customMenu) {
                const menuConfig = this.get(customMenu.xmlid);
                log.logic("open", () => ({
                    xmlid: customMenu.xmlid,
                    openWidget: !!menuConfig.openWidget,
                    getProps: !!menuConfig.getProps,
                    dynamicProps: customMenu.dynamicProps,
                }));
                if (menuConfig.openWidget) {
                    return menuConfig.openWidget(services);
                }
                const endProps = log.perf("open getProps", () => ({
                    xmlid: customMenu.xmlid,
                }));
                const menuProps = {
                    ...(menuConfig.getProps && (await menuConfig.getProps(services))),
                    ...customMenu.dynamicProps,
                };
                endProps();
                log.lifecycle("open dialog", () => ({
                    xmlid: customMenu.xmlid,
                    component: menuConfig.Component?.name,
                }));
                return dialog.add(menuConfig.Component, menuProps);
            },
            addCustomMenus(sections) {
                const filteredSections = [];
                for (const section of sections) {
                    const isWebsiteCustomMenu = !!this.get(section.xmlid);
                    const displayWebsiteCustomMenu =
                        isWebsiteCustomMenu &&
                        website.isRestrictedEditor &&
                        this.get(section.xmlid).isDisplayed(env);
                    if (!isWebsiteCustomMenu || displayWebsiteCustomMenu) {
                        let subSections = [];
                        if (section.childrenTree.length) {
                            subSections = this.addCustomMenus(section.childrenTree);
                        }
                        if (section.xmlid === "website.custom_menu_edit_menu") {
                            filteredSections.push(
                                ...website.currentWebsite.metadata.contentMenus.map(
                                    (menu, index) => ({
                                        ...section,
                                        name: _t("Edit %s", menu[0]),
                                        dynamicProps: { rootID: parseInt(menu[1], 10) },
                                        id: `${section.id}-${index}`,
                                    }),
                                ),
                            );
                        } else {
                            filteredSections.push(
                                Object.assign({}, section, {
                                    childrenTree: subSections,
                                }),
                            );
                        }
                    }
                }
                for (const section of filteredSections) {
                    section.childrenTree = section.childrenTree.filter(
                        (tree) => !(tree.children.length && !tree.childrenTree.length),
                    );
                }
                return filteredSections;
            },
        };
    },
};
registry.category("services").add("website_custom_menus", websiteCustomMenus);

registry.category("website_custom_menus").add("website.menu_edit_menu", {
    Component: EditMenuDialog,
    isDisplayed: (env) =>
        !!env.services.website.currentWebsite &&
        env.services.website.isDesigner &&
        !env.services.website.currentWebsite.metadata.translatable,
});
registry.category("website_custom_menus").add("website.menu_optimize_seo", {
    Component: OptimizeSEODialog,
    isDisplayed: (env) =>
        env.services.website.currentWebsite &&
        env.services.website.isRestrictedEditor &&
        !!env.services.website.currentWebsite.metadata.canOptimizeSeo,
});
registry.category("website_custom_menus").add("website.menu_ace_editor", {
    openWidget: (services) => (services.website.context.showResourceEditor = true),
    isDisplayed: (env) =>
        env.services.website.currentWebsite &&
        env.services.website.currentWebsite.metadata.viewXmlid &&
        !env.services.ui.isSmall,
});
registry.category("website_custom_menus").add("website.menu_page_properties", {
    Component: PagePropertiesDialog,
    isDisplayed: (env) =>
        env.services.website.currentWebsite &&
        env.services.website.isDesigner &&
        !!env.services.website.currentWebsite.metadata.mainObject,
    getProps: async ({ orm, website }) => {
        const mainObject = website.currentWebsite.metadata.mainObject;
        const isPage = mainObject.model === "website.page";
        const model = isPage
            ? "website.page.properties"
            : "website.page.properties.base";
        const websiteId = website.currentWebsite.id;
        const getNormalizedPath = () => {
            let path = website.currentLocation;
            if (!path) {
                log.logic(
                    "page properties: no current location, fall back to metadata path",
                    () => ({
                        metadataPath: website.currentWebsite.metadata.path,
                    }),
                );
                try {
                    path = new URL(website.currentWebsite.metadata.path).pathname;
                } catch {
                    path = website.currentWebsite.metadata.path || "/";
                }
            }
            if (path && !path.startsWith("/")) {
                path = `/${path}`;
            }
            return path || "/";
        };
        log.logic("page properties getProps", () => ({
            model,
            isPage,
            mainObject,
            websiteId,
        }));
        const recordValues = isPage
            ? {
                  target_model_id: mainObject.id,
                  website_id: websiteId,
              }
            : {
                  target_model_id: `${mainObject.model},${mainObject.id}`,
                  url: getNormalizedPath(),
                  website_id: websiteId,
              };
        return {
            resId: await orm.call(model, "create", [recordValues]),
            resModel: model,
            onRecordSaved: async (record) => {
                const endSaved = log.perf("page properties onRecordSaved", () => ({
                    isPage,
                }));
                const page = isPage
                    ? (
                          await orm.read(
                              "website.page",
                              [mainObject.id],
                              ["website_id", "url"],
                          )
                      )[0]
                    : undefined;
                endSaved(() => ({ page }));
                return website.goToWebsite({
                    websiteId: page?.website_id?.[0] ?? website.currentWebsite.id,
                    path: page?.url ?? website.currentWebsite.metadata.path,
                });
            },
        };
    },
});
registry.category("website_custom_menus").add("website.custom_menu_edit_menu", {
    Component: EditMenuDialog,
    isDisplayed: (env) =>
        env.services.website.currentWebsite &&
        env.services.website.currentWebsite.metadata.contentMenus &&
        env.services.website.currentWebsite.metadata.contentMenus.length,
});
