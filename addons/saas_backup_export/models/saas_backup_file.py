# -*- coding: utf-8 -*-
import hashlib
import hmac
import logging
import os
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaasBackupFile(models.Model):
    """Représente un fichier de sauvegarde ZIP trouvé sur le système de fichiers.

    L'action 'Scanner les backups' parcourt le dossier racine configuré
    et crée/met à jour un enregistrement par fichier ZIP trouvé.
    """
    _name = 'saas.backup.file'
    _description = 'Fichier de sauvegarde SaaS'
    _order = 'backup_date desc, client_name'

    name = fields.Char(string='Nom du fichier', readonly=True)
    client_name = fields.Char(string='Client', readonly=True, index=True)
    file_path = fields.Char(string='Chemin complet', readonly=True)
    file_size_mb = fields.Float(string='Taille (Mo)', readonly=True, digits=(16, 2))
    backup_date = fields.Datetime(string='Date de sauvegarde', readonly=True)
    state = fields.Selection([
        ('available', 'Disponible'),
        ('missing', 'Fichier manquant'),
    ], string='État', default='available', readonly=True)
    download_token = fields.Char(
        string='Token de téléchargement',
        readonly=True,
        copy=False,
        help="Token sécurisé utilisé pour l'URL de téléchargement.",
    )
    download_url = fields.Char(
        string="Lien de téléchargement",
        compute='_compute_download_url',
    )

    # -------------------------------------------------------------------------
    # Compute
    # -------------------------------------------------------------------------

    def _compute_download_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for record in self:
            if record.download_token and record.state == 'available':
                record.download_url = (
                    f"{base_url}/saas/backup/download"
                    f"?id={record.id}&token={record.download_token}"
                )
            else:
                record.download_url = False

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_scan_backups(self, domain=None):
        """Scanne le dossier racine configuré et crée/met à jour les enregistrements
        pour chaque fichier ZIP trouvé dans les sous-dossiers clients.
        """
        config = self.env['saas.backup.config'].search([], limit=1)
        if not config:
            raise UserError(_(
                "Aucune configuration trouvée. Veuillez d'abord configurer "
                "le dossier racine des backups dans Configuration > Paramètres Backup."
            ))

        base_path = config.base_path.rstrip('/')
        if not os.path.isdir(base_path):
            raise UserError(_(
                "Le dossier %(path)s n'existe pas ou n'est pas accessible.",
                path=base_path,
            ))

        found_paths = set()
        created = updated = 0

        # Parcourir les sous-dossiers (un par client)
        for client_folder in sorted(os.listdir(base_path)):
            client_path = os.path.join(base_path, client_folder)
            if not os.path.isdir(client_path):
                continue

            # Chercher tous les fichiers ZIP dans le dossier client
            for filename in sorted(os.listdir(client_path)):
                if not filename.lower().endswith('.zip'):
                    continue

                full_path = os.path.join(client_path, filename)
                found_paths.add(full_path)

                stat = os.stat(full_path)
                size_mb = stat.st_size / (1024 * 1024)
                backup_date = datetime.fromtimestamp(stat.st_mtime)

                existing = self.search([('file_path', '=', full_path)], limit=1)
                if existing:
                    existing.write({
                        'file_size_mb': size_mb,
                        'backup_date': backup_date,
                        'state': 'available',
                    })
                    updated += 1
                else:
                    token = self._generate_token(full_path)
                    self.create({
                        'name': filename,
                        'client_name': client_folder,
                        'file_path': full_path,
                        'file_size_mb': size_mb,
                        'backup_date': backup_date,
                        'state': 'available',
                        'download_token': token,
                    })
                    created += 1

        # Marquer comme manquants les fichiers qui n'existent plus
        missing = self.search([
            ('file_path', 'not in', list(found_paths)),
            ('state', '=', 'available'),
        ])
        missing.write({'state': 'missing'})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Scan terminé"),
                'message': _(
                    "%(created)s fichier(s) ajouté(s), %(updated)s mis à jour, "
                    "%(missing)s marqué(s) comme manquant(s).",
                    created=created,
                    updated=updated,
                    missing=len(missing),
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_download(self):
        """Retourne l'URL de téléchargement sécurisée pour le fichier backup."""
        self.ensure_one()
        if self.state == 'missing':
            raise UserError(_("Le fichier de sauvegarde n'existe plus sur le serveur."))
        if not self.download_url:
            raise UserError(_("Impossible de générer le lien de téléchargement."))
        return {
            'type': 'ir.actions.act_url',
            'url': self.download_url,
            'target': 'self',
        }

    def action_open_restore_wizard(self):
        """Ouvre le wizard de restauration pré-rempli avec ce fichier backup."""
        self.ensure_one()
        if self.state == 'missing':
            raise UserError(_(
                "Le fichier de sauvegarde n'existe plus sur le serveur."
            ))
        # Proposer un nom de base à partir du dossier client
        suggested_name = (
            self.client_name
            .replace('.odoo.sunsoftbf.com', '')
            .replace('.', '_')
            .replace('-', '_')
            .lower()
        ) if self.client_name else ''

        wizard = self.env['saas.backup.restore.wizard'].create({
            'backup_file_id': self.id,
            'db_name': suggested_name,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'saas.backup.restore.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
            'name': _('Restauration — %s') % self.name,
        }

    def action_mark_missing(self):
        """Vérifie si le fichier existe encore et met à jour l'état."""
        for record in self:
            if os.path.isfile(record.file_path):
                record.state = 'available'
            else:
                record.state = 'missing'

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @api.model
    def _generate_token(self, file_path):
        """Génère un token HMAC sécurisé unique pour chaque fichier."""
        secret = self.env['ir.config_parameter'].sudo().get_param(
            'database.secret', default='odoo-secret'
        )
        return hmac.new(
            secret.encode(),
            file_path.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()
