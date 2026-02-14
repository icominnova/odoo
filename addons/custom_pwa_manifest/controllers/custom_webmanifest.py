from odoo.addons.web.controllers import webmanifest
from odoo import http

class CustomWebManifest(webmanifest.WebManifest):
    @http.route('/web/manifest.webmanifest', type='http', auth='public', methods=['GET'], readonly=True)
    def webmanifest(self):
        """ Surcharge du manifeste PWA pour personnalisation """
        return http.request.make_json_response(self._get_webmanifest(), {
            'Content-Type': 'application/manifest+json'
        })

    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        appinfo = http.request.env['custom.pwa.appinfo'].sudo().search([], order='id desc', limit=1)
        if appinfo:
            if appinfo.name:
                manifest['name'] = appinfo.name
            if appinfo.description:
                manifest['description'] = appinfo.description
            if appinfo.background_color:
                manifest['background_color'] = appinfo.background_color
            if appinfo.theme_color:
                manifest['theme_color'] = appinfo.theme_color
        # Icônes dynamiques ou fallback statique
        images = http.request.env['custom.pwa.manifest.image'].sudo().search([])
        if images:
            manifest['icons'] = []
            for img in images:
                manifest['icons'].append({
                    "src": f"/web/image/custom.pwa.manifest.image/{img.id}/image",
                    "sizes": img.sizes,
                    "type": img.type,
                    "purpose": img.purpose,
                })
        
        screenshots = http.request.env['custom.pwa.manifest.screenshot'].sudo().search([])
        if screenshots:
            manifest['screenshots'] = []
            for shot in screenshots:
                manifest['screenshots'].append({
                    "src": f"/web/image/custom.pwa.manifest.screenshot/{shot.id}/image",
                    "sizes": shot.sizes,
                    "type": shot.type,
                    "form_factor": shot.form_factor,
                    "label": shot.label or shot.name,
                })
                
        return manifest
