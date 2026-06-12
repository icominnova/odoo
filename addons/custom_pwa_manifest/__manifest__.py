# -*- coding: utf-8 -*-
{
    'name': 'Custom PWA Manifest',
    'version': '1.0',
    'category': 'Website',
    'summary': 'Personnalisation du manifeste PWA(Progressive Web App) Odoo',
    'description': 'Surcharge le manifeste PWA pour permettre une personnalisation facile.',
    'author': 'Alain GANSONRE',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'views/assets.xml',
        'views/custom_pwa_title_views.xml',
        'views/custom_pwa_image_views.xml',
        'views/custom_pwa_manifest_views.xml',
        'views/custom_pwa_manifest_image_views.xml',
        'views/custom_pwa_manifest_screenshot_views.xml',
    ],
    'installable': True,
    'auto_install': False,
}
