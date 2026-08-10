{
    "name": "Attribute Mixins",
    "version": "19.0.1.1.0",
    "category": "Hidden",
    "summary": "Reusable EAV and classification mixins: attribute, attribute value, attribute line and numeric band.",
    "description": """
Abstract building blocks for an Entity-Attribute-Value family: an attribute
(the dimension being profiled), its values, and a line binding one attribute
and its chosen values to a subject record.

Ships mixins only -- no concrete models, no data, no views. A consumer
declares the three concrete models, points them at each other, and inherits
the coherence rules from here. The pattern mirrors
``product.template.attribute.line``, generalised so that subjects other than
product templates can carry an attribute set.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "base",
    ],
    "pre_init_hook": "pre_init_hook",
}
