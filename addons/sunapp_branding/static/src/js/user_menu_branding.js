import { registry } from "@web/core/registry";

const userMenuRegistry = registry.category("user_menuitems");

if (userMenuRegistry.contains("odoo_account")) {
    userMenuRegistry.remove("odoo_account");
}
