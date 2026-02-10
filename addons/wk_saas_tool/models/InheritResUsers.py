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
#################################################################################s

from odoo import api, fields, models, tools, SUPERUSER_ID, _
from odoo.exceptions import AccessDenied, UserError
import logging
from odoo.http import request
_logger = logging.getLogger(__name__)


class Users(models.Model):
    _inherit = "res.users"

    def _check_credentials(self, credential, env):
        """ Override this method to plug additional authentication methods"""

        if not (credential['type'] == 'password' and credential.get('password')):
            raise AccessDenied()

        env = env or {}
        interactive = env.get('interactive', True)

        if interactive or not self.env.user._rpc_api_keys_only():
            if 'interactive' not in env:
                _logger.warning(
                    "_check_credentials without 'interactive' env key, assuming interactive login. \
                    Check calls and overrides to ensure the 'interactive' key is properly set in \
                    all _check_credentials environments"
                )

            self.env.cr.execute(
                "SELECT COALESCE(password, '') FROM res_users WHERE id=%s",
                [self.env.user.id]
            )
            [hashed] = self.env.cr.fetchone()
            valid, replacement = self._crypt_context()\
                .verify_and_update(credential['password'], hashed)
            if replacement is not None:
                self._set_encrypted_password(self.env.user.id, replacement)
                if request and self == self.env.user:
                    self.env.flush_all()
                    self.env.registry.clear_cache()
                    # update session token so the user does not get logged out
                    new_token = self.env.user._compute_session_token(request.session.sid)
                    request.session.session_token = new_token

            if valid or hashed == credential['password']:
                return {
                    'uid': self.env.user.id,
                    'auth_method': 'password',
                    'mfa': 'default',
                }

        if not interactive:
            # 'rpc' scope does not really exist, we basically require a global key (scope NULL)
            if self.env['res.users.apikeys']._check_credentials(scope='rpc', key=credential['password']) == self.env.uid:
                return {
                    'uid': self.env.user.id,
                    'auth_method': 'apikey',
                    'mfa': 'default',
                }

            if self.env.user._rpc_api_keys_only():
                _logger.info(
                    "Invalid API key or password-based authentication attempted for a non-interactive (API) "
                    "context that requires API key authentication only."
                )

        raise AccessDenied()
        
    
    @api.model
    def get_user_signup_token(self, user_id):
        user = self.env['res.users'].browse([int(user_id)])
        partner = user.partner_id
        partner.signup_prepare(signup_type="signup")
        signup_token = partner.sudo()._generate_signup_token()
        return signup_token
        

    @api.model_create_multi
    def create(self, val_list):
        for vals in val_list:
            if vals.get('sel_groups_1_10_11') and vals['sel_groups_1_10_11'] == 1:
                try:
                    max_users = self.env['ir.config_parameter'].sudo().get_param('user.max_users')
                    is_user = self.env['ir.config_parameter'].sudo().get_param('user.count')
                    if is_user == 'True' and int(max_users) != 0 and int(max_users) != -1:
                        total_active_users = self.env['res.users'].sudo().search([('active', '=', True), ('share', '=', False)])
                        if len(total_active_users) >= int(max_users):
                            raise Exception("User limit exceeds! Can't Create user.")
                except Exception as e:
                    raise UserError("{} Please contact admin.".format(e))
        res = super(Users, self).create(val_list)
        return res
    
    def write(self, vals):
        if vals.get('sel_groups_1_10_11') and vals['sel_groups_1_10_11'] == 1:
            try:
                max_users = self.env['ir.config_parameter'].sudo().get_param('user.max_users')
                is_user = self.env['ir.config_parameter'].sudo().get_param('user.count')
                if is_user == 'True' and int(max_users) != 0 and int(max_users) != -1:
                    total_active_users = self.env['res.users'].sudo().search([('active', '=', True), ('share', '=', False)])
                    if len(total_active_users) >= int(max_users):
                        raise Exception("User limit exceeds! Can't Create user.")
            except Exception as e:
                raise UserError("{} Please contact admin.".format(e))
        res = super(Users, self).write(vals)
        return res

    
    def copy_data(self, default=None):
        if self.has_group('base.group_user'):
            try:
                max_users = self.env['ir.config_parameter'].sudo().get_param('user.max_users')
                is_user = self.env['ir.config_parameter'].sudo().get_param('user.count')
                if is_user == 'True' and int(max_users) != 0 and int(max_users) != -1:
                    total_active_users = self.sudo().search([('active', '=', True), ('share', '=', False)])
                    if len(total_active_users) >= int(max_users):
                        raise Exception("User limit exceeds! Can't Create user.")
            except Exception as e:
                raise UserError("{} Please contact admin.".format(e))
        return super(Users, self).copy_data(default=default)
