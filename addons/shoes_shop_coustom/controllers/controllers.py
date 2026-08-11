# from odoo import http


# class ShoesShopCoustom(http.Controller):
#     @http.route('/shoes_shop_coustom/shoes_shop_coustom', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/shoes_shop_coustom/shoes_shop_coustom/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('shoes_shop_coustom.listing', {
#             'root': '/shoes_shop_coustom/shoes_shop_coustom',
#             'objects': http.request.env['shoes_shop_coustom.shoes_shop_coustom'].search([]),
#         })

#     @http.route('/shoes_shop_coustom/shoes_shop_coustom/objects/<model("shoes_shop_coustom.shoes_shop_coustom"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('shoes_shop_coustom.object', {
#             'object': obj
#         })

