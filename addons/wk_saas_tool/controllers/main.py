# -*- coding: utf-8 -*-
#################################################################################
# Author      : Webkul Software Pvt. Ltd. (<https://webkul.com/>)
# Copyright(c): 2015-Present Webkul Software Pvt. Ltd.
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://store.webkul.com/license.html/>
#################################################################################
import os
import datetime
import pytz
import shutil
import subprocess
import tempfile
import json

import odoo
from werkzeug.exceptions import BadRequest
from odoo.http import request
from odoo import http

from odoo.tools.misc import find_pg_tool, exec_pg_environ

import logging,werkzeug,json
import requests

_logger = logging.getLogger(__name__)


class SaaSLogin(http.Controller):

    
    @http.route('/saas/login', type='http', auth='public', website=True)
    def autologin(self, **kw):
        """login user via Odoo Account provider
        QUERY : SELECT COALESCE(password, '') FROM res_users WHERE id=1;
        import base64
        base64.b64encode(s.encode('utf-8'))
        """
        db = request.params.get('db') and request.params.get('db').strip()
        dbname = kw.pop('db', None)
        redirect_url = kw.pop('redirect_url', '/web')
        login = kw.pop('login', 'admin')
        password = kw.pop('passwd', None)
        if not dbname:
            return BadRequest()
        credential = {'login': login, 'password': password, 'type': 'password'}
        auth_info = request.session.authenticate(request.env, credential)
        request.params['login_success'] = True

        return http.request.redirect(redirect_url)

    @http.route('/install/saas/modules', type='http', auth='public',methods=['GET'])
    def install_saas_module(self,**kw):
        response = {'status':False,'missed_module_list': None}
        try:
            request.env['ir.config_parameter'].sudo().install_modules()
            response['status'] = True
            response['missed_module_list'] = request.env['ir.config_parameter'].sudo().get_param("missed_module_list")
        except Exception as e:
            _logger.info(f" Some Error Occured : Could Not Install Modules completely!!")
        body = json.dumps(response,default=lambda o: o.__dict__)
        headers = [
                ('Content-Type', 'application/json; charset=utf-8'),
                ('Content-Length', len(body))
                ]
        return werkzeug.wrappers.Response(body, headers=headers)

    @http.route('/saas/database/backup', type='http', auth="none", methods=['POST'], csrf=False)
    def saas_db_backup(self, **kwargs):
        master_pwd = kwargs.get('master_pwd')
        dbname = kwargs.get('name')
        backup_format = kwargs.get('backup_format') or 'zip'
        response = None
        user = request.env['res.users'].sudo().browse([2])
        tz = pytz.timezone(user.tz) if user.tz else pytz.utc
        time_now = pytz.utc.localize(datetime.datetime.now()).astimezone(tz)
        ts = time_now.strftime("%m-%d-%Y-%H-%M-%S")
        filename = "%s_%s.%s" % (dbname, ts, backup_format)
        try:
            odoo.service.db.check_super(master_pwd)
            dump_stream = self.dump_db(dbname, None, backup_format)
            response = request.make_response(dump_stream)
            response.headers['Content-Disposition'] = f"attachment; filename={filename}"
            response.mimetype = 'application/octet-stream'
        except Exception as e:
            error = "Database backup error: %s" % (str(e) or repr(e))
            _logger.warning('Database.backup --- %r', error)
            response = request.make_response(error)
            response.mimetype = 'text/html'

        response.headers['Backup-Filename'] = filename
        response.headers['Backup-Time'] = time_now.strftime("%m-%d-%Y-%H:%M:%S")
        return response
    
    def dump_db_manifest(self, cr):
        pg_version = "%d.%d" % divmod(cr._obj.connection.server_version / 100, 100)
        cr.execute("SELECT name, latest_version FROM ir_module_module WHERE state = 'installed'")
        modules = dict(cr.fetchall())
        manifest = {
            'odoo_dump': '1',
            'db_name': cr.dbname,
            'version': odoo.release.version,
            'version_info': odoo.release.version_info,
            'major_version': odoo.release.major_version,
            'pg_version': pg_version,
            'modules': modules,
        }
        return manifest
    
    def dump_db(self, db_name, stream, backup_format='zip'):
        """Dump database `db` into file-like object `stream` if stream is None
        return a file object with the dump """

        _logger.info('DUMP DB: %s format %s', db_name, backup_format)

        cmd = [find_pg_tool('pg_dump'), '--no-owner', db_name]
        env = exec_pg_environ()

        if backup_format == 'zip':
            with tempfile.TemporaryDirectory() as dump_dir:
                filestore = odoo.tools.config.filestore(db_name)
                if os.path.exists(filestore):
                    shutil.copytree(filestore, os.path.join(dump_dir, 'filestore'))
                with open(os.path.join(dump_dir, 'manifest.json'), 'w') as fh:
                    db = odoo.sql_db.db_connect(db_name)
                    with db.cursor() as cr:
                        json.dump(self.dump_db_manifest(cr), fh, indent=4)
                cmd.insert(-1, '--file=' + os.path.join(dump_dir, 'dump.sql'))
                subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)
                if stream:
                    odoo.tools.osutil.zip_dir(dump_dir, stream, include_dir=False, fnct_sort=lambda file_name: file_name != 'dump.sql')
                else:
                    t=tempfile.TemporaryFile()
                    odoo.tools.osutil.zip_dir(dump_dir, t, include_dir=False, fnct_sort=lambda file_name: file_name != 'dump.sql')
                    t.seek(0)
                    return t
        else:
            cmd.insert(-1, '--format=c')
            stdout = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE).stdout
            if stream:
                shutil.copyfileobj(stdout, stream)
            else:
                return stdout

    @http.route('/update/saas/modules/list', type='http', auth='public',methods=['GET'])
    def update_saas_module_list(self,**kw):
        response = {'status':False,'missed_module_list': None}
        try:
            totalModuleList = request.env['ir.config_parameter'].sudo().get_param('module_list') and request.env['ir.config_parameter'].sudo().get_param('module_list').split(',')
            subscribed_status = request.env['ir.config_parameter'].sudo().update_subscribed_list(totalModuleList)
            response['status'] = True
            response['missed_module_list'] = request.env['ir.config_parameter'].sudo().get_param("missed_module_list")
        except Exception as e:
            _logger.info(f" Some Error Occured : Could Not Install Modules completely!!")
        body = json.dumps(response,default=lambda o: o.__dict__)
        headers = [
                ('Content-Type', 'application/json; charset=utf-8'),
                ('Content-Length', len(body))
                ]
        return werkzeug.wrappers.Response(body, headers=headers)
