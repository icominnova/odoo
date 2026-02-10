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
{
  "name"                 :  "Saas Tool",
  "summary"              :  "Saas Tool",
  "category"             :  "Extra",
  "version"              :  "1.0.2",
  "sequence"             :  1,
  "author"               :  "Webkul Software Pvt. Ltd.",
  "license"              :  "Other proprietary",
  "description"          :  """Saas tools""",
  "depends"              :  [
                                'base', 'web', 'auth_signup',
                            ],
  "data"                  : [
                              'data/ir_config_parameter.xml',
                              'data/install_module_cron.xml',
                              'views/ir_module_view.xml',
                            ],
  'post_init_hook'         : 'post_init_hook',
  'assets'               : {
                             'web.assets_backend': [
                               "wk_saas_tool/static/src/css/trial_information.css",
                               "wk_saas_tool/static/src/js/trial_information.js"
                            ],
    
    },
  "application"          :  True,
  "installable"          :  True,
  "auto_install"         :  True,
}
