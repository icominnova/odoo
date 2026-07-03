{
    "name": "SaaS Bulk Restart",
    "version": "19.0.1.0.0",
    "category": "SaaS",
    "summary": "Restart several SaaS clients from the list view",
    "author": "Sunsoft",
    "license": "LGPL-3",
    "depends": ["odoo_saas_kit"],
    "data": [
        "security/ir.model.access.csv",
        "views/saas_bulk_restart_views.xml",
        "views/saas_client_actions.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
