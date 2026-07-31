{
    'name': "company_team",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': "Ce module sert à maintenir et gérer correctement une équipe en entreprise",

    'author': "Sougrinooma",
    'license':"LGPL-3",
    'website': "",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '19.0.1.0',
    'application':True,
    'installable':True,

    # any module necessary for this one to work correctly
    'depends': ['base'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/team_views.xml',
        'views/menu.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}

