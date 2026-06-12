from odoo.addons.web.controllers import webmanifest
from odoo import http


DEFAULT_APP_NAME = "SunApp"
DEFAULT_APP_DESCRIPTION = "SunApp"
DEFAULT_BACKGROUND_COLOR = "#FFFFFF"
DEFAULT_THEME_COLOR = "#000000"
DEFAULT_PWA_ICONS = [
    {
        "src": "/custom_pwa_manifest/static/src/img/pwa-icon-192.png",
        "sizes": "192x192",
        "type": "image/png",
        "purpose": "any",
    },
    {
        "src": "/custom_pwa_manifest/static/src/img/pwa-icon-512.png",
        "sizes": "512x512",
        "type": "image/png",
        "purpose": "any",
    },
    {
        "src": "/custom_pwa_manifest/static/src/img/pwa-icon-maskable-512.png",
        "sizes": "512x512",
        "type": "image/png",
        "purpose": "maskable",
    },
]


class CustomWebManifest(webmanifest.WebManifest):
    @http.route('/web/manifest.webmanifest', type='http', auth='public', methods=['GET'], readonly=True)
    def webmanifest(self):
        """ Surcharge du manifeste PWA pour personnalisation """
        return http.request.make_json_response(self._get_webmanifest(), {
            'Content-Type': 'application/manifest+json',
            'Cache-Control': 'no-store',
        })

    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        manifest['name'] = DEFAULT_APP_NAME
        manifest['short_name'] = DEFAULT_APP_NAME
        manifest['description'] = DEFAULT_APP_DESCRIPTION
        manifest['background_color'] = DEFAULT_BACKGROUND_COLOR
        manifest['theme_color'] = DEFAULT_THEME_COLOR
        manifest['icons'] = DEFAULT_PWA_ICONS
        
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

    def _get_scoped_app_name(self, app_id):
        return DEFAULT_APP_NAME

    def _get_scoped_app_icons(self, app_id):
        return DEFAULT_PWA_ICONS
