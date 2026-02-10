# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2016-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#   See LICENSE file for full copyright and licensing details.
#   License URL : <https://store.webkul.com/license.html/>
# 
#################################################################################

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging 

_logger = logging.getLogger(__name__)


class IrModuleModule(models.AbstractModel):
    _inherit = "ir.module.module"

    is_subscribed = fields.Boolean(string="Is Subscribed", default=lambda self: self.get_default_value_for_is_subscribed()) 
    
    @api.model
    def get_default_value_for_is_subscribed(self): 
        try: 
            restrict_app_list = self.env['ir.config_parameter'].sudo().get_param('restrict_app_list') 
            if restrict_app_list !="True": 
                return True 
            return False
        except: 
            return True

    def get_recursive_dependencies(self, module_name, visited=None):
        """Recursively get dependencies of a module"""
        if visited is None:
            visited = set()
        if module_name in visited:
            return set()
        visited.add(module_name)
        module = self.search([('name', '=', module_name)], limit=1)
        if not module:
            return visited  # module not found
        for dep_name in module.dependencies_id.mapped('name'):
            self.get_recursive_dependencies(dep_name, visited)
        return visited - {module_name}
