# -*- coding: utf-8 -*-
#
# Copyright (c) 2008, Stephen Hansen
# Copyright (c) 2009, Robert Corsaro
# Copyright (c) 2012, Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from trac.config import Option
from trac.core import Component, implements
from trac.notification.api import IEmailAddressResolver

from announcer.api import _, IAnnouncementPreferenceProvider
from announcer.util.settings import SubscriptionSetting


class DefaultDomainEmailResolver(Component):

    implements(IEmailAddressResolver)

    default_domain = Option('announcer', 'email_default_domain', '',
        """Default host/domain to append to address that do not specify one.
        """)

    def get_address_for_session(self, sid, authenticated):
        if self.default_domain:
            return '%s@%s' % (sid, self.default_domain)
        return None


class SessionEmailResolver(Component):

    implements(IEmailAddressResolver)

    def get_address_for_session(self, sid, authenticated):
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute("""
                SELECT value
                  FROM session_attribute
                 WHERE sid=%s
                   AND authenticated=%s
                   AND name=%s
            """, (sid, int(authenticated), 'email'))
            result = cursor.fetchone()
            if result:
                return result[0]
            return None


class SpecifiedEmailResolver(Component):

    implements(IEmailAddressResolver, IAnnouncementPreferenceProvider)

    def get_address_for_session(self, sid, authenticated):
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute("""
                SELECT value
                  FROM session_attribute
                 WHERE sid=%s
                   AND authenticated=1
                   AND name=%s
            """, (sid, 'announcer_specified_email'))
            result = cursor.fetchone()
            if result:
                return result[0]
            return None

    # IAnnouncementDistributor methods

    def get_announcement_preference_boxes(self, req):
        if req.authname != 'anonymous':
            yield 'emailaddress', _("Announcement Email Address")

    def render_announcement_preference_box(self, req, panel):
        if req.method == 'POST':
            opt = req.args.get('specified_email', '')
            req.session['announcer_specified_email'] = opt
        specified = req.session.get('announcer_specified_email', '')
        data = dict(specified_email=specified)
        return 'prefs_announcer_emailaddress.html', data


class SpecifiedXmppResolver(Component):

    implements(IEmailAddressResolver, IAnnouncementPreferenceProvider)

    def __init__(self):
        self.setting = SubscriptionSetting(self.env, 'specified_xmpp')

    def get_address_for_session(self, sid, authed):
        return self.setting.get_user_setting(sid)[1]

    # IAnnouncementDistributor methods

    def get_announcement_preference_boxes(self, req):
        if req.authname != 'anonymous':
            yield 'xmppaddress', _("Announcement XMPP Address")

    def render_announcement_preference_box(self, req, panel):
        if req.method == 'POST':
            self.setting.set_user_setting(req.session,
                                          req.args.get('specified_xmpp'))
        specified = self.setting.get_user_setting(req.session.sid)[1] or ''
        data = dict(specified_xmpp=specified, )
        return 'prefs_announcer_xmppaddress.html', data
