{
    'name': "shoes_shop_coustom",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
Facture de chaussures
    """,

    'author': "Sougrinooma",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '19.0.1.0.1',
    'application':True,
    'installable':True,
    'license':'LGPL-3',

    # any module necessary for this one to work correctly
    'depends': [
        "account",
        "web"
        ],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/invoice_report_views.xml',
        'views/templates.xml',
        'data/report_layout.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],

    'assets' : {
       'web.report_assets_common' : [
            'shoes_shop_coustom/static/src/css/invoice_style.css'
        ]
    },

}

