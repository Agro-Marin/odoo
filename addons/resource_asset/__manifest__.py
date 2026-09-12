{
    "name": "Assets",
    "version": "1.0",
    "category": "Hidden",
    "summary": "A physical thing as a resource: identity, lifecycle, meters, custody",
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "resource",
        "mail",
        "uom",
    ],
    "data": [
        "security/resource_asset_security.xml",
        "security/ir.model.access.csv",
        "data/resource_asset_identifier_type_data.xml",
        "data/resource_asset_kind_data.xml",
        "views/resource_asset_kind_views.xml",
        "views/resource_asset_identifier_type_views.xml",
        "views/resource_asset_meter_views.xml",
        "views/resource_asset_views.xml",
        "views/menuitems.xml",
    ],
}
