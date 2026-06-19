{
    "name": "SunApp SaaS Contract Automation",
    "version": "19.0.1.0.5",
    "category": "Sales",
    "summary": "Confirme automatiquement les contrats SaaS issus du formulaire client",
    "author": "Alain Gansonré",
    "depends": ["sunapp_customer_form", "odoo_saas_kit"],
    "data": [
        "data/ir_cron.xml",
        "views/customer_form_templates.xml",
        "views/sale_order_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
