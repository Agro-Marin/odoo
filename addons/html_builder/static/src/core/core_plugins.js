/** @odoo-module native */
import {
    MAIN_PLUGINS as MAIN_EDITOR_PLUGINS,
    NO_EMBEDDED_COMPONENTS_FALLBACK_PLUGINS,
} from "@html_editor/plugin_sets";
import { removePlugins } from "@html_builder/utils/utils";
import { AnchorPlugin } from "./anchor/anchor_plugin.js";
import { BuilderActionsPlugin } from "./builder_actions_plugin.js";
import { BuilderComponentPlugin } from "./builder_component_plugin.js";
import { BuilderOptionsPlugin } from "./builder_options_plugin.js";
import { BuilderOverlayPlugin } from "./builder_overlay/builder_overlay_plugin.js";
import { CachedModelPlugin } from "./cached_model_plugin.js";
import { ClonePlugin } from "./clone_plugin.js";
import { ColorUIPlugin } from "./color_ui_plugin.js";
import { ImagePlugin } from "./image_plugin.js";
import { IconPlugin } from "./icon_plugin.js";
import { CoreBuilderActionPlugin } from "./core_builder_action_plugin.js";
import { CompositeActionPlugin } from "./composite_action_plugin.js";
import { CustomizeTabPlugin } from "./customize_tab_plugin.js";
import { DisableSnippetsPlugin } from "./disable_snippets_plugin.js";
import { DragAndDropPlugin } from "./drag_and_drop_plugin.js";
import { DropZonePlugin } from "./drop_zone_plugin.js";
import { DropZoneSelectorPlugin } from "./dropzone_selector_plugin.js";
import { GridLayoutPlugin } from "./grid_layout/grid_layout_plugin.js";
import { MediaWebsitePlugin } from "./media_website_plugin.js";
import { MovePlugin } from "./move_plugin.js";
import { OperationPlugin } from "./operation_plugin.js";
import { OverlayButtonsPlugin } from "./overlay_buttons/overlay_buttons_plugin.js";
import { RemovePlugin } from "./remove_plugin.js";
import { SavePlugin } from "./save_plugin.js";
import { SaveSnippetPlugin } from "./save_snippet_plugin.js";
import { SetupEditorPlugin } from "./setup_editor_plugin.js";
import { CoreSetupEditorPlugin } from "./core_setup_editor_plugin.js";
import { VisibilityPlugin } from "./visibility_plugin.js";
import { FieldChangeReplicationPlugin } from "./field_change_replication_plugin.js";
import { BuilderContentEditablePlugin } from "./builder_content_editable_plugin.js";
import { ImageFieldPlugin } from "@html_builder/plugins/image_field_plugin";
import { MonetaryFieldPlugin } from "@html_builder/plugins/monetary_field_plugin";
import { DateTimeFieldPlugin } from "@html_builder/plugins/date_time_field_plugin";
import { Many2OneOptionPlugin } from "@html_builder/plugins/many2one_option_plugin";
import { VersionErrorPlugin } from "./version_error_plugin.js";

const mainEditorPluginsToRemove = [
    "PowerButtonsPlugin",
    "DoubleClickImagePreviewPlugin",
    "SeparatorPlugin",
    "StarPlugin",
    "BannerPlugin",
    "MoveNodePlugin",
    "FontFamilyPlugin",
    "SelectionPlaceholderPlugin",
    // Replaced plugins:
    "ColorUIPlugin",
    "ImagePlugin",
    "IconPlugin",
];

export const MAIN_PLUGINS = [
    ...removePlugins(
        [...MAIN_EDITOR_PLUGINS, ...NO_EMBEDDED_COMPONENTS_FALLBACK_PLUGINS],
        mainEditorPluginsToRemove
    ),
    ColorUIPlugin,
    ImagePlugin,
    IconPlugin,
];

export const CORE_PLUGINS = [
    ...MAIN_PLUGINS,
    BuilderOptionsPlugin,
    BuilderActionsPlugin,
    BuilderComponentPlugin,
    OperationPlugin,
    BuilderOverlayPlugin,
    OverlayButtonsPlugin,
    MovePlugin,
    GridLayoutPlugin,
    DragAndDropPlugin,
    RemovePlugin,
    ClonePlugin,
    SaveSnippetPlugin,
    AnchorPlugin,
    DropZonePlugin,
    DisableSnippetsPlugin,
    MediaWebsitePlugin,
    SetupEditorPlugin,
    CoreSetupEditorPlugin,
    SavePlugin,
    VisibilityPlugin,
    DropZoneSelectorPlugin,
    CachedModelPlugin,
    CoreBuilderActionPlugin,
    CompositeActionPlugin,
    CustomizeTabPlugin,
    FieldChangeReplicationPlugin,
    BuilderContentEditablePlugin,
    ImageFieldPlugin,
    MonetaryFieldPlugin,
    DateTimeFieldPlugin,
    Many2OneOptionPlugin,
    VersionErrorPlugin,
];
