from . import models
from . import wizard


def post_init_hook(env):
    env["saas.bulk.restart.wizard"]._install_or_update_list_button()
