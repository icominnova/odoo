# -*- coding: utf-8 -*-
{
    'name': 'SaaS Backup Export',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Liste et téléchargement des fichiers de sauvegarde SaaS',
    'description': """
        Module autonome qui scanne le dossier de stockage des backups SaaS
        (/opt/odoo/Odoo-SAAS-Data/ par défaut) et permet de :
        - Lister les fichiers de sauvegarde par client
        - Télécharger les ZIP directement depuis l'interface Odoo
        - Restaurer une sauvegarde dans une base existante ou nouvelle
    """,
    'author': 'Alain Gansonré',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/saas_backup_config_views.xml',
        'views/saas_backup_restore_wizard_views.xml',
        'views/saas_backup_file_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
