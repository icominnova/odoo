# -*- coding: utf-8 -*-
import logging
import os

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SaasBackupController(http.Controller):

    @http.route(
        '/saas/backup/download',
        type='http',
        auth='user',          # L'utilisateur doit être connecté
        methods=['GET'],
        csrf=False,
    )
    def download_backup(self, id=None, token=None, **kwargs):
        """Endpoint sécurisé pour télécharger un fichier de sauvegarde ZIP.

        Vérifie :
        - que l'utilisateur est connecté (auth='user')
        - que l'id et le token correspondent à un enregistrement existant
        - que le token HMAC est valide (anti-falsification d'URL)
        - que le fichier existe bien sur le système de fichiers
        """
        if not id or not token:
            return request.not_found()

        # Récupérer l'enregistrement
        try:
            backup = request.env['saas.backup.file'].sudo().browse(int(id))
        except Exception:
            return request.not_found()

        if not backup.exists():
            return request.not_found()

        # Vérification du token de sécurité
        if backup.download_token != token:
            _logger.warning(
                "Tentative de téléchargement avec un token invalide pour le backup id=%s",
                id,
            )
            return request.not_found()

        # Vérifier que le fichier existe sur le disque
        file_path = backup.file_path
        if not file_path or not os.path.isfile(file_path):
            backup.sudo().write({'state': 'missing'})
            return request.not_found()

        _logger.info(
            "Téléchargement du backup '%s' par l'utilisateur '%s'",
            backup.name,
            request.env.user.name,
        )

        # Lire et streamer le fichier ZIP vers le navigateur
        file_size = os.path.getsize(file_path)
        with open(file_path, 'rb') as f:
            content = f.read()

        headers = [
            ('Content-Type', 'application/zip'),
            ('Content-Disposition', f'attachment; filename="{backup.name}"'),
            ('Content-Length', str(file_size)),
        ]
        return request.make_response(content, headers=headers)
