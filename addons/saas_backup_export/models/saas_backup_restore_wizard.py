# -*- coding: utf-8 -*-
import logging
import os

import odoo.service.db as db_service
from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, UserError

_logger = logging.getLogger(__name__)


class SaasBackupRestoreWizard(models.TransientModel):
    """Assistant de restauration d'une sauvegarde SaaS.

    Deux modes :
    - 'new'       → Restaure le backup dans une nouvelle base de données
                    (la base ne doit pas encore exister)
    - 'overwrite' → Supprime la base existante et la recrée depuis le backup
                    (⚠️ toutes les données actuelles sont perdues)
    """
    _name = 'saas.backup.restore.wizard'
    _description = 'Assistant de restauration Backup SaaS'

    backup_file_id = fields.Many2one(
        'saas.backup.file',
        string='Fichier de sauvegarde',
        readonly=True,
        required=True,
    )
    backup_name = fields.Char(
        related='backup_file_id.name',
        string='Fichier',
        readonly=True,
    )
    backup_client = fields.Char(
        related='backup_file_id.client_name',
        string='Client',
        readonly=True,
    )
    backup_date = fields.Datetime(
        related='backup_file_id.backup_date',
        string='Date du backup',
        readonly=True,
    )

    mode = fields.Selection([
        ('new', 'Nouvelle base de données'),
        ('overwrite', '⚠️ Écraser une base existante'),
    ], string='Mode de restauration', required=True, default='new')

    db_name = fields.Char(
        string='Nom de la base cible',
        required=True,
        help="Nom de la base PostgreSQL. Pour 'Nouvelle base', elle ne doit pas encore exister. "
             "Pour 'Écraser', elle sera supprimée puis recréée.",
    )
    master_password = fields.Char(
        string='Mot de passe maître Odoo',
        required=True,
        password=True,
        help="Le mot de passe maître du serveur Odoo (admin_passwd dans odoo.conf).",
    )
    neutralize = fields.Boolean(
        string='Neutraliser la base',
        default=True,
        help="Génère un nouvel identifiant unique (UUID) pour la base restaurée. "
             "Recommandé pour éviter les conflits avec la base d'origine.",
    )
    confirm_overwrite = fields.Boolean(
        string="Je confirme vouloir supprimer la base existante",
        default=False,
    )

    # -------------------------------------------------------------------------
    # Onchange
    # -------------------------------------------------------------------------

    @api.onchange('backup_file_id')
    def _onchange_backup_file_id(self):
        if self.backup_file_id and self.backup_file_id.client_name:
            # Proposer le nom du client comme nom de base par défaut
            self.db_name = self.backup_file_id.client_name.replace(
                '.odoo.sunsoftbf.com', ''
            ).replace('.', '_').replace('-', '_').lower()

    # -------------------------------------------------------------------------
    # Action principale
    # -------------------------------------------------------------------------

    def action_restore(self):
        """Lance la restauration après vérification des paramètres."""
        self.ensure_one()

        # 1. Vérifier le mot de passe maître
        try:
            db_service.check_super(self.master_password)
        except AccessDenied:
            raise UserError(_(
                "Mot de passe maître incorrect. "
                "Vérifiez la valeur de 'admin_passwd' dans odoo.conf."
            ))

        # 2. Vérifier le fichier backup
        file_path = self.backup_file_id.file_path
        if not file_path or not os.path.isfile(file_path):
            self.backup_file_id.write({'state': 'missing'})
            raise UserError(_(
                "Le fichier de sauvegarde '%(name)s' n'existe plus sur le serveur.",
                name=self.backup_file_id.name,
            ))

        db_name = self.db_name.strip()
        if not db_name:
            raise UserError(_("Le nom de la base cible est obligatoire."))

        # 3. Mode 'overwrite' : demander confirmation et supprimer l'existante
        if self.mode == 'overwrite':
            if not self.confirm_overwrite:
                raise UserError(_(
                    "Vous devez cocher la case de confirmation pour écraser une base existante."
                ))
            existing_dbs = db_service.list_dbs(True)
            if db_name in existing_dbs:
                _logger.warning(
                    "Restauration SaaS : suppression de la base '%s' demandée par '%s'",
                    db_name, self.env.user.name,
                )
                try:
                    db_service.exp_drop(db_name)
                except Exception as e:
                    raise UserError(_(
                        "Impossible de supprimer la base '%(db)s' : %(error)s",
                        db=db_name, error=str(e),
                    ))

        # 4. Lancer la restauration
        _logger.info(
            "Restauration SaaS : '%s' → base '%s' par '%s'",
            self.backup_file_id.name, db_name, self.env.user.name,
        )
        try:
            db_service.restore_db(
                db_name,
                file_path,
                copy=self.neutralize,
                neutralize_database=self.neutralize,
            )
        except Exception as e:
            raise UserError(_(
                "Erreur lors de la restauration : %(error)s",
                error=str(e),
            ))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Restauration réussie"),
                'message': _(
                    "La base '%(db)s' a été restaurée depuis '%(file)s'.",
                    db=db_name,
                    file=self.backup_file_id.name,
                ),
                'type': 'success',
                'sticky': True,
            },
        }
