# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import logging
import os
import re
import uuid
import zipfile
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaasBackupFileMigrationMixin(models.Model):
    _inherit = 'saas.backup.file'

    source_type = fields.Selection([
        ('local', 'Backup local'),
        ('imported', 'Import externe'),
    ], string='Origine', default='local', readonly=True, index=True)
    sha256 = fields.Char(string='SHA-256', readonly=True, copy=False)
    analysis_state = fields.Selection([
        ('pending', 'À analyser'),
        ('valid', 'Valide'),
        ('invalid', 'Invalide'),
    ], string='Analyse', default='pending', readonly=True, index=True)
    manifest_version = fields.Char(string='Version Odoo', readonly=True)
    manifest_database = fields.Char(string='Base source', readonly=True)
    manifest_module_count = fields.Integer(string='Modules du backup', readonly=True)
    manifest_modules_json = fields.Text(string='Modules (JSON)', readonly=True)
    has_dump = fields.Boolean(string='dump.sql présent', readonly=True)
    has_filestore = fields.Boolean(string='Filestore présent', readonly=True)
    analysis_message = fields.Text(string="Rapport d'analyse", readonly=True)
    analyzed_at = fields.Datetime(string='Analysé le', readonly=True)

    def action_open_import_wizard(self):
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_('Accès réservé aux administrateurs système.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Importer une sauvegarde ZIP'),
            'res_model': 'saas.backup.import.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_analyze_backup(self):
        for record in self:
            record._analyze_backup_zip()
        if len(self) == 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Analyse terminée'),
                    'message': self.analysis_message or _('Sauvegarde analysée.'),
                    'type': 'success' if self.analysis_state == 'valid' else 'danger',
                    'sticky': self.analysis_state != 'valid',
                },
            }
        return True

    def action_open_saas_migration(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_('Accès réservé aux administrateurs système.'))
        if self.analysis_state != 'valid':
            self._analyze_backup_zip()
        if self.analysis_state != 'valid':
            raise UserError(self.analysis_message or _('La sauvegarde est invalide.'))
        migration = self.env['saas.backup.migration'].create({
            'backup_file_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Migration SaaS'),
            'res_model': 'saas.backup.migration',
            'res_id': migration.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _manifest_modules(self):
        self.ensure_one()
        try:
            values = json.loads(self.manifest_modules_json or '[]')
        except Exception:
            return []
        return sorted({str(value).strip() for value in values if str(value).strip()})

    def _analyze_backup_zip(self):
        self.ensure_one()
        file_path = self.file_path
        vals = {
            'sha256': False,
            'analysis_state': 'invalid',
            'manifest_version': False,
            'manifest_database': False,
            'manifest_module_count': 0,
            'manifest_modules_json': '[]',
            'has_dump': False,
            'has_filestore': False,
            'analysis_message': False,
            'analyzed_at': fields.Datetime.now(),
        }
        try:
            if not file_path or not os.path.isfile(file_path):
                raise UserError(_('Le fichier ZIP est introuvable.'))
            if not zipfile.is_zipfile(file_path):
                raise UserError(_('Le fichier sélectionné n’est pas une archive ZIP valide.'))

            digest = hashlib.sha256()
            with open(file_path, 'rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            vals['sha256'] = digest.hexdigest()

            manifest = {}
            module_names = []
            has_dump = False
            has_filestore = False
            with zipfile.ZipFile(file_path, 'r') as archive:
                for member in archive.infolist():
                    raw_name = (member.filename or '').replace('\\', '/')
                    normalized = os.path.normpath(raw_name).replace('\\', '/')
                    if (
                        not raw_name
                        or raw_name.startswith('/')
                        or normalized == '..'
                        or normalized.startswith('../')
                    ):
                        raise UserError(_('Archive ZIP dangereuse : chemin interdit %(path)s.', path=raw_name))
                    if normalized == 'dump.sql':
                        has_dump = True
                    if normalized.startswith('filestore/') and not member.is_dir():
                        has_filestore = True

                if 'manifest.json' not in archive.namelist():
                    raise UserError(_('Le fichier ZIP ne contient pas manifest.json.'))
                manifest_info = archive.getinfo('manifest.json')
                if manifest_info.file_size > 20 * 1024 * 1024:
                    raise UserError(_('manifest.json est anormalement volumineux.'))
                manifest = json.loads(archive.read('manifest.json').decode('utf-8'))

            if not has_dump:
                raise UserError(_('Le fichier ZIP ne contient pas dump.sql.'))

            modules = manifest.get('modules') or {}
            if isinstance(modules, dict):
                module_names = list(modules.keys())
            elif isinstance(modules, (list, tuple)):
                for value in modules:
                    if isinstance(value, str):
                        module_names.append(value)
                    elif isinstance(value, dict) and value.get('name'):
                        module_names.append(value['name'])
            module_names = sorted({str(name).strip() for name in module_names if str(name).strip()})
            if not module_names:
                raise UserError(_('manifest.json ne contient aucune liste de modules exploitable.'))

            version = (
                manifest.get('version')
                or manifest.get('major_version')
                or manifest.get('server_version')
                or ''
            )
            if isinstance(version, (list, tuple)):
                version = '.'.join(str(item) for item in version[:2])
            version_text = str(version or '')
            if version_text and not (version_text.startswith('19.0') or version_text == '19'):
                raise UserError(_('Version Odoo incompatible : %s. Seules les sauvegardes Odoo 19 sont autorisées.') % version_text)

            inferred_name = re.sub(r'_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$', '', os.path.splitext(self.name or '')[0])
            source_db = (
                manifest.get('db_name')
                or manifest.get('database')
                or manifest.get('database_name')
                or inferred_name
                or self.database_name
                or self.client_name
                or ''
            )

            vals.update({
                'analysis_state': 'valid',
                'manifest_version': version_text,
                'manifest_database': str(source_db or ''),
                'manifest_module_count': len(module_names),
                'manifest_modules_json': json.dumps(module_names, ensure_ascii=False),
                'has_dump': has_dump,
                'has_filestore': has_filestore,
                'analysis_message': _(
                    'ZIP valide — dump.sql: %(dump)s, filestore: %(filestore)s, modules: %(modules)s, SHA-256: %(sha)s',
                    dump='OK' if has_dump else 'NON',
                    filestore='OK' if has_filestore else 'ABSENT',
                    modules=len(module_names),
                    sha=vals['sha256'],
                ),
            })
            if source_db:
                vals['database_name'] = str(source_db)
                vals['client_name'] = str(source_db)
        except Exception as error:
            vals['analysis_state'] = 'invalid'
            vals['analysis_message'] = str(error)
            _logger.exception('Analyse du backup SaaS impossible pour %s', file_path)
        self.write(vals)
        return self.analysis_state == 'valid'


class SaasBackupImportWizard(models.TransientModel):
    _name = 'saas.backup.import.wizard'
    _description = 'Import ZIP Backup SaaS'

    upload_file = fields.Binary(string='Fichier ZIP', required=True)
    upload_filename = fields.Char(string='Nom du fichier', required=True)

    def action_import(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_('Accès réservé aux administrateurs système.'))

        filename = os.path.basename((self.upload_filename or '').strip())
        if not filename.lower().endswith('.zip'):
            raise UserError(_('Seuls les fichiers .zip sont acceptés.'))
        if not re.fullmatch(r'[A-Za-z0-9._() -]+\.zip', filename, flags=re.IGNORECASE):
            raise UserError(_('Le nom du fichier contient des caractères non autorisés.'))

        raw_b64 = self.upload_file or b''
        max_mb = int(self.env['ir.config_parameter'].sudo().get_param(
            'saas_backup_export.import_max_mb', '2048'
        ))
        estimated_bytes = (len(raw_b64) * 3) // 4
        if estimated_bytes > max_mb * 1024 * 1024:
            raise UserError(_('Le fichier dépasse la limite configurée de %(size)s Mo.', size=max_mb))

        try:
            payload = base64.b64decode(raw_b64, validate=True)
        except Exception as error:
            raise UserError(_('Le fichier envoyé est invalide : %s') % error)

        import_root = self.env['ir.config_parameter'].sudo().get_param(
            'saas_backup_export.import_path', '/opt/odoo/backups/imports'
        )
        import_root = os.path.realpath(os.path.abspath(os.path.expanduser(import_root)))
        os.makedirs(import_root, exist_ok=True)
        if not os.access(import_root, os.W_OK):
            raise UserError(_('Le dossier d’import n’est pas accessible en écriture : %s') % import_root)

        stem, ext = os.path.splitext(filename)
        inferred_db = re.sub(r'_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$', '', stem)
        unique_name = '%s_%s%s' % (
            re.sub(r'[^A-Za-z0-9._-]+', '_', stem)[:160],
            uuid.uuid4().hex[:10],
            ext.lower(),
        )
        destination = os.path.realpath(os.path.join(import_root, unique_name))
        if os.path.commonpath([import_root, destination]) != import_root:
            raise UserError(_('Chemin d’import refusé.'))

        with open(destination, 'xb') as stream:
            stream.write(payload)

        if not zipfile.is_zipfile(destination):
            os.unlink(destination)
            raise UserError(_('Le fichier importé n’est pas une archive ZIP valide.'))

        stat = os.stat(destination)
        backup_model = self.env['saas.backup.file']
        record = backup_model.create({
            'name': filename,
            'database_name': inferred_db,
            'client_name': inferred_db,
            'file_path': destination,
            'file_size_mb': stat.st_size / (1024 * 1024),
            'backup_date': datetime.fromtimestamp(stat.st_mtime),
            'relative_path': os.path.join('imports', unique_name),
            'state': 'available',
            'download_token': backup_model._generate_token(destination),
            'source_type': 'imported',
            'analysis_state': 'pending',
        })
        record._analyze_backup_zip()
        if record.analysis_state != 'valid':
            raise UserError(record.analysis_message or _('Le ZIP importé est invalide.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Fichier de sauvegarde'),
            'res_model': 'saas.backup.file',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }
