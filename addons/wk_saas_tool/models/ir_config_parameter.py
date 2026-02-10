# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2016-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#   See LICENSE file for full copyright and licensing details.
#   License URL : <https://store.webkul.com/license.html/>
# 
#################################################################################

from odoo import api, fields, models
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)


class IrConfig(models.Model):
        _inherit = 'ir.config_parameter'

        @api.model
        def get_config_data(self):
            data = dict()
            self.env.cr.commit()
            data['trial.is_trial_enabled'] = self.env['ir.config_parameter'].sudo().get_param('trial.is_trial_enabled')
            trial_period = int(self.env['ir.config_parameter'].sudo().get_param('trial.trial_period'))
            data['trial.purchase_link'] = self.env['ir.config_parameter'].sudo().get_param('trial.purchase_link')
            create_date = self.env['ir.config_parameter'].sudo().get_param('database.create_date')
            create_date = datetime.strptime(create_date, '%Y-%m-%d %H:%M:%S')
            trial_date = create_date + timedelta(days=trial_period)
            data['contract.is_expired'] = self.env['ir.config_parameter'].sudo().get_param('contract.is_expired')
            _logger.info("##########################   %r         "%data)
            today_date = datetime.now()
            trial_period = (trial_date - today_date).days + 1
            if trial_period < 0 or data['contract.is_expired'] == 'True':
                data['trial.trial_period'] = str(0)
            else:
                data['trial.trial_period'] = str(trial_period)
            return data

     
        def install_modules(self):
            moduleList = self.env['ir.config_parameter'].sudo().get_param('missed_module_list') and self.env['ir.config_parameter'].sudo().get_param('missed_module_list').split(',')
            restrict_app_list = self.env['ir.config_parameter'].sudo().get_param('restrict_app_list')
            if restrict_app_list =="True":
                AllmoduleList = self.env['ir.config_parameter'].sudo().get_param('module_list') and self.env['ir.config_parameter'].sudo().get_param('module_list').split(',')
                subscribed_status = self.update_subscribed_list(AllmoduleList)
            else:
                all_modules = self.env['ir.module.module'].sudo().search([])
                all_modules.write({
                        'is_subscribed': True
                    })
            if moduleList and moduleList !=["False"]:
                module_objs = self.env['ir.module.module'].search([('name','in',moduleList)],limit=3)
                installed =[]
                not_installed=moduleList
                if not module_objs:
                    not_installed = []
                for rec in module_objs:
                    try:
                        rec.button_install()
                        self.env['base.module.upgrade'].upgrade_module()
                        installed.append(rec.name)
                        not_installed.remove(rec.name)
                    except Exception as e:
                        _logger.info(f"Error While Installing {rec.name} : {e}")
                moduleList= "False"
                if len(not_installed):
                    moduleList = ",".join(not_installed)
                self.env['ir.config_parameter'].sudo().set_param('missed_module_list',moduleList)
                self.env['ir.module.module'].search([('name','=','wk_saas_tool')]).button_immediate_upgrade()
            else:
                try:
                    self.env.ref('wk_saas_tool.install_module_cron').active = False
                except Exception as e:
                    _logger.error(f" Error while deactivating the Install Module cron  {e}")

        
        def activate_cron(self):
            try:
                self.env.ref('wk_saas_tool.install_module_cron').active = True
                self.env.ref('wk_saas_tool.install_module_cron').nextcall = datetime.now()+timedelta(minutes=1)
                return True
            except Exception as e:
                _logger.error(f" Error while Activating the Install Module Cron  {e}")
                return False

        def update_subscribed_list(self, module_names):
            if module_names != ['False']:
                modules = self.env['ir.module.module'].search([('name','in', module_names)])
                if not module_names or (module_names and len(modules) > 0):
                    all_modules = self.env['ir.module.module'].sudo().search([('name', '!=', 'wk_saas_tool')])
                    all_modules.write({
                        'is_subscribed': False
                    })
                depends_list = []
                if module_names:
                    for module in modules:
                        module.is_subscribed = True
                        dependencies_list = module.get_recursive_dependencies(module.name)
                        depends_list += dependencies_list

                    depends_list = list(set(depends_list))
                    depends_modules = self.env['ir.module.module'].search([('name','in', depends_list)])
                    depends_modules.write({
                        'is_subscribed': True
                    })
            self.env['ir.module.module'].search([('name','=','wk_saas_tool')]).button_immediate_upgrade()
            self.activate_cron()
            return True
