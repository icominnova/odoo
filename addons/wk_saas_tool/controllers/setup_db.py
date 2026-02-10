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

from odoo.http import Request
from odoo.http import root, get_default_session, db_filter, db_list
import werkzeug.exceptions
import logging
import base64

_logger = logging.getLogger(__name__)


def _get_session_and_dbname(self):
    sid = self.httprequest._session_id__
    if not sid or not root.session_store.is_valid_key(sid):
        session = root.session_store.new()
    else:
        session = root.session_store.get(sid)
        session.sid = sid  # in case the session was not persisted

    for key, val in get_default_session().items():
        session.setdefault(key, val)
    if not session.context.get('lang'):
        session.context['lang'] = self.default_lang()

    dbname = None
    host = self.httprequest.environ['HTTP_HOST']
    header_dbname = self.httprequest.headers.get('X-Odoo-Database')
    if session.db and db_filter([session.db], host=host):
        dbname = session.db
        if header_dbname and header_dbname != dbname:
            e = ("Cannot use both the session_id cookie and the "
                    "x-odoo-database header.")
            raise werkzeug.exceptions.Forbidden(e)
    elif header_dbname:
        session.can_save = False  # stateless
        if db_filter([header_dbname], host=host):
            dbname = header_dbname
    else:
        all_dbs = db_list(force=True, host=host)
        if len(all_dbs) == 1:
            dbname = all_dbs[0]  # monodb

    if self.httprequest.args.get('db'):
        dbname = self.httprequest.args.get('db')

    if session.db != dbname:
        if session.db and dbname != self.httprequest.args.get('db'):
            _logger.warning("Logged into database %r, but dbfilter rejects it; logging session out.", session.db)
            session.logout(keep_db=False)
        session.db = dbname

    if not session.db:
        dbname = self.httprequest.args.get('db')
        session.db = dbname

    session.is_dirty = False
    return session, dbname

Request._get_session_and_dbname = _get_session_and_dbname
