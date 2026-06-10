# -*- coding: utf-8 -*-
{
    "name": "SunApp Branding",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Remplace les signatures Odoo visibles par SunApp",
    "author": "Alain Gansonré",
    "depends": ["web", "website", "mail_bot"],
    "data": [
        "data/odoobot_data.xml",
        "views/branding_templates.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sunapp_branding/static/src/xml/res_config_edition.xml",
            (
                "after",
                "web/static/src/webclient/user_menu/user_menu_items.js",
                "sunapp_branding/static/src/js/user_menu_branding.js",
            ),
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
