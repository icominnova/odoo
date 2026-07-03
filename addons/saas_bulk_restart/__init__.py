from . import models
from . import wizard


def post_init_hook(env):
    View = env["ir.ui.view"].sudo()
    ModelData = env["ir.model.data"].sudo()

    if ModelData.search([
        ("module", "=", "saas_bulk_restart"),
        ("name", "=", "view_saas_client_bulk_restart_header"),
    ], limit=1):
        return

    list_view = View.search([
        ("model", "=", "saas.client"),
        ("type", "in", ("list", "tree")),
        ("mode", "=", "primary"),
    ], order="priority, id", limit=1)
    if not list_view:
        list_view = View.search([
            ("model", "=", "saas.client"),
            ("type", "in", ("list", "tree")),
        ], order="priority, id", limit=1)
    if not list_view:
        return

    root_tag = "list" if list_view.type == "list" else "tree"
    inherited_view = View.create({
        "name": "saas.client.bulk.restart.header",
        "model": "saas.client",
        "type": list_view.type,
        "mode": "extension",
        "inherit_id": list_view.id,
        "arch_db": """
            <data>
                <xpath expr="//%s" position="inside">
                    <header>
                        <button
                            name="action_open_bulk_restart_wizard"
                            type="object"
                            string="Restart Selected"
                            class="btn-primary"
                        />
                    </header>
                </xpath>
            </data>
        """ % root_tag,
    })
    ModelData.create({
        "module": "saas_bulk_restart",
        "name": "view_saas_client_bulk_restart_header",
        "model": "ir.ui.view",
        "res_id": inherited_view.id,
        "noupdate": True,
    })
