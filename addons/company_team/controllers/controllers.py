# from odoo import http


# class CompanyTeam(http.Controller):
#     @http.route('/company_team/company_team', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/company_team/company_team/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('company_team.listing', {
#             'root': '/company_team/company_team',
#             'objects': http.request.env['company_team.company_team'].search([]),
#         })

#     @http.route('/company_team/company_team/objects/<model("company_team.company_team"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('company_team.object', {
#             'object': obj
#         })

