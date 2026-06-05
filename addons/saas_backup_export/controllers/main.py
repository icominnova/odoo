# -*- coding: utf-8 -*-
import logging
import os
import tempfile
import zipfile
from datetime import datetime
from hmac import compare_digest

from odoo import http
from odoo.http import Response, content_disposition, request

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
        if not request.env.user.has_group('base.group_system'):
            return request.not_found()

        # Récupérer l'enregistrement
        try:
            backup = request.env['saas.backup.file'].sudo().browse(int(id))
        except Exception:
            return request.not_found()

        if not backup.exists():
            return request.not_found()

        # Vérification du token de sécurité
        if not compare_digest(backup.download_token or '', token or ''):
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

        file_size = os.path.getsize(file_path)
        headers = [
            ('Content-Type', 'application/zip'),
            ('Content-Disposition', content_disposition(backup.name or os.path.basename(file_path))),
            ('Content-Length', str(file_size)),
        ]
        return Response(
            self._file_iterator(file_path),
            headers=headers,
            direct_passthrough=True,
        )

    @http.route(
        '/saas/backup/download_archive',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
    )
    def download_backup_archive(self, ids=None, token=None, **kwargs):
        if not ids or not token:
            return request.not_found()
        if not request.env.user.has_group('base.group_system'):
            return request.not_found()

        try:
            record_ids = [int(record_id) for record_id in ids.split(',') if record_id]
        except ValueError:
            return request.not_found()

        backups = request.env['saas.backup.file'].sudo().browse(record_ids).exists()
        if len(backups) != len(set(record_ids)):
            return request.not_found()

        expected_token = request.env['saas.backup.file']._generate_archive_token(backups)
        if not compare_digest(expected_token or '', token or ''):
            _logger.warning("Tentative de téléchargement archive avec un token invalide: %s", ids)
            return request.not_found()

        missing = backups.filtered(lambda backup: not backup.file_path or not os.path.isfile(backup.file_path))
        if missing:
            missing.write({'state': 'missing'})
            return request.not_found()

        archive_path = self._build_archive(backups)
        archive_name = datetime.now().strftime('saas_backups_%Y%m%d_%H%M%S.zip')
        headers = [
            ('Content-Type', 'application/zip'),
            ('Content-Disposition', content_disposition(archive_name)),
            ('Content-Length', str(os.path.getsize(archive_path))),
        ]
        return Response(
            self._file_iterator(archive_path, unlink=True),
            headers=headers,
            direct_passthrough=True,
        )

    @http.route(
        '/saas/backup/download_browser_lines',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
    )
    def download_browser_lines(self, ids=None, token=None, **kwargs):
        if not ids or not token:
            return request.not_found()
        if not request.env.user.has_group('base.group_system'):
            return request.not_found()

        try:
            line_ids = [int(line_id) for line_id in ids.split(',') if line_id]
        except ValueError:
            return request.not_found()

        lines = request.env['saas.backup.browser.line'].sudo().browse(line_ids).exists()
        if len(lines) != len(set(line_ids)):
            return request.not_found()

        expected_token = self._generate_browser_lines_token(lines)
        if not compare_digest(expected_token or '', token or ''):
            _logger.warning("Tentative de téléchargement filestore avec un token invalide: %s", ids)
            return request.not_found()

        existing_lines = lines.filtered(lambda line: line.full_path and os.path.exists(line.full_path))
        if not existing_lines:
            return request.not_found()

        archive_path = self._build_archive_from_browser_lines(existing_lines)
        archive_name = datetime.now().strftime('saas_filestore_%Y%m%d_%H%M%S.zip')
        headers = [
            ('Content-Type', 'application/zip'),
            ('Content-Disposition', content_disposition(archive_name)),
            ('Content-Length', str(os.path.getsize(archive_path))),
        ]
        return Response(
            self._file_iterator(archive_path, unlink=True),
            headers=headers,
            direct_passthrough=True,
        )

    def _build_archive(self, backups):
        fd, archive_path = tempfile.mkstemp(prefix='saas_backups_', suffix='.zip')
        os.close(fd)
        used_names = set()
        with zipfile.ZipFile(archive_path, mode='w', compression=zipfile.ZIP_STORED) as archive:
            for backup in backups.sorted(lambda record: (record.client_name or '', record.name or '')):
                archive.write(backup.file_path, self._archive_name(backup, used_names))
        return archive_path

    def _build_archive_from_browser_lines(self, lines):
        fd, archive_path = tempfile.mkstemp(prefix='saas_filestore_', suffix='.zip')
        os.close(fd)
        used_names = set()
        with zipfile.ZipFile(archive_path, mode='w', compression=zipfile.ZIP_STORED) as archive:
            for line in lines.sorted(lambda record: (record.client_name or '', record.name or '')):
                if os.path.isdir(line.full_path):
                    self._write_folder_to_archive(archive, line.full_path, line.client_name or line.name, used_names)
                elif os.path.isfile(line.full_path):
                    archive.write(line.full_path, self._unique_archive_name(line.name, used_names))
        return archive_path

    def _write_folder_to_archive(self, archive, folder_path, root_name, used_names):
        root_name = (root_name or os.path.basename(folder_path)).replace('\\', '/').strip('/')
        for root, _dirs, files in os.walk(folder_path):
            for filename in sorted(files, key=str.lower):
                full_path = os.path.join(root, filename)
                relative_path = os.path.relpath(full_path, folder_path).replace('\\', '/')
                archive_name = self._unique_archive_name('%s/%s' % (root_name, relative_path), used_names)
                archive.write(full_path, archive_name)

    def _unique_archive_name(self, name, used_names):
        name = (name or 'filestore').replace('\\', '/').lstrip('/')
        if not name or name.startswith('../') or name == '..':
            name = 'filestore'

        base, extension = os.path.splitext(name)
        candidate = name
        counter = 2
        while candidate in used_names:
            candidate = '%s_%s%s' % (base, counter, extension)
            counter += 1
        used_names.add(candidate)
        return candidate

    def _generate_browser_lines_token(self, lines):
        payload = '|'.join(
            '%s:%s' % (line.id, line.full_path or '')
            for line in lines.sorted('id')
        )
        secret = request.env['ir.config_parameter'].sudo().get_param(
            'database.secret', default='odoo-secret'
        )
        return request.env['saas.backup.file']._generate_token(payload + secret)

    def _archive_name(self, backup, used_names):
        name = (backup.relative_path or backup.name or os.path.basename(backup.file_path)).replace('\\', '/')
        name = name.lstrip('/')
        if not name or name.startswith('../') or name == '..':
            name = backup.name or os.path.basename(backup.file_path)
        if backup.client_name and '/' not in name:
            name = '%s/%s' % (backup.client_name, name)

        base, extension = os.path.splitext(name)
        candidate = name
        counter = 2
        while candidate in used_names:
            candidate = '%s_%s%s' % (base, counter, extension)
            counter += 1
        used_names.add(candidate)
        return candidate

    def _file_iterator(self, file_path, unlink=False):
        try:
            with open(file_path, 'rb') as file_handle:
                while True:
                    chunk = file_handle.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
        finally:
            if unlink:
                try:
                    os.unlink(file_path)
                except OSError:
                    _logger.warning("Impossible de supprimer l'archive temporaire %s", file_path)
