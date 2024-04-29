# -*- coding: utf-8 -*-
#
# Copyright (c) 2008, Stephen Hansen
# Copyright (c) 2009,2010 Robert Corsaro
# Copyright (c) 2012, Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import operator
import re
from genshi.filters.transform import Transformer
from pkg_resources import resource_filename

from trac.core import Component, ExtensionPoint, implements
from trac.prefs.api import IPreferencePanelProvider
from trac.web.api import ITemplateStreamFilter
from trac.web.chrome import Chrome, ITemplateProvider, add_stylesheet

from announcer.api import _, IAnnouncementDefaultSubscriber, \
                          IAnnouncementDistributor, IAnnouncementFormatter, \
                          IAnnouncementPreferenceProvider, \
                          IAnnouncementSubscriber
from announcer.model import Subscription


def truth(v):
    if v in (False, 'False', 'false', 0, '0', ''):
        return None
    return True


class AnnouncerTemplateProvider(Component):
    """Provides templates and static resources for the announcer plugin."""

    implements(ITemplateProvider)

    abstract = True

    # ITemplateProvider methods

    def get_htdocs_dirs(self):
        """Return the absolute path of a directory containing additional
        static resources (such as images, style sheets, etc).
        """
        return [('announcer', resource_filename(__name__, 'htdocs'))]

    def get_templates_dirs(self):
        """Return the absolute path of the directory containing the provided
        Genshi templates.
        """
        return [resource_filename(__name__, 'templates')]


class AnnouncerPreferences(AnnouncerTemplateProvider):

    implements(IPreferencePanelProvider)

    preference_boxes = ExtensionPoint(IAnnouncementPreferenceProvider)

    # IPreferencePanelProvider methods

    def get_preference_panels(self, req):
        if self.preference_boxes:
            yield ('announcer', _("Announcements"))

    def _get_boxes(self, req):
        for pr in self.preference_boxes:
            boxes = pr.get_announcement_preference_boxes(req)
            if boxes:
                for boxname, boxlabel in boxes:
                    if boxname == 'general_wiki' and \
                            'WIKI_VIEW' not in req.perm:
                        continue
                    if (boxname == 'legacy' or
                            boxname == 'joinable_groups') and \
                            'TICKET_VIEW' not in req.perm:
                        continue
                    yield ((boxname, boxlabel) +
                           pr.render_announcement_preference_box(req,
                                                                 boxname))

    def render_preference_panel(self, req, panel, path_info=None):
        streams = []
        chrome = Chrome(self.env)
        for name, label, template, data in self._get_boxes(req):
            streams.append((label, chrome.render_template(
                req, template, data, fragment=True
            )))

        if req.method == 'POST':
            req.redirect(req.href.prefs('announcer'))

        add_stylesheet(req, 'announcer/css/announcer_prefs.css')
        if hasattr(chrome, 'jenv'):
            return 'prefs_announcer.html', {"boxes": streams}, None
        else:
            return 'prefs_announcer.html', {"boxes": streams}


class SubscriptionManagementPanel(AnnouncerTemplateProvider):

    implements(IPreferencePanelProvider, ITemplateStreamFilter)

    subscribers = ExtensionPoint(IAnnouncementSubscriber)
    default_subscribers = ExtensionPoint(IAnnouncementDefaultSubscriber)
    distributors = ExtensionPoint(IAnnouncementDistributor)
    formatters = ExtensionPoint(IAnnouncementFormatter)

    def __init__(self):
        self.post_handlers = {
            'add-rule': self._add_rule,
            'delete-rule': self._delete_rule,
            'move-rule': self._move_rule,
            'set-format': self._set_format
        }

    # IPreferencePanelProvider methods

    def get_preference_panels(self, req):
        yield 'subscriptions', _("Subscriptions")

    def render_preference_panel(self, req, panel, path_info=None):
        if req.method == 'POST':
            method_arg = req.args.get('method', '')
            m = re.match('^([^_]+)_(.+)', method_arg)
            if m:
                method, arg = m.groups()
                method_func = self.post_handlers.get(method)
                if method_func:
                    method_func(arg, req)
                else:
                    pass
            else:
                pass
            # Refresh page after saving changes.
            req.redirect(req.href.prefs('subscriptions'))

        data = {'rules': {}, 'subscribers': [],
                'formatters': ('text/plain', 'text/html'),
                'selected_format': {}, 'adverbs': ('always', 'never')}

        desc_map = {}

        for i in self.subscribers:
            if not i.description():
                continue
            if not req.session.authenticated and i.requires_authentication():
                continue
            data['subscribers'].append({
                'class': i.__class__.__name__,
                'description': i.description()
            })
            desc_map[i.__class__.__name__] = i.description()

        for i in self.distributors:
            for j in i.transports():
                data['rules'][j] = []
                for r in Subscription.find_by_sid_and_distributor(
                        self.env, req.session.sid,
                        req.session.authenticated, j):
                    if desc_map.get(r['class']):
                        data['rules'][j].append({
                            'id': r['id'],
                            'adverb': r['adverb'],
                            'description': desc_map[r['class']],
                            'priority': r['priority']
                        })
                        data['selected_format'][j] = r['format']

        data['default_rules'] = {}
        defaults = []
        for i in self.default_subscribers:
            defaults.extend(i.default_subscriptions())

        for r in sorted(defaults, key=operator.itemgetter(2)):
            klass, dist, _, adverb = r
            if not data['default_rules'].get(dist):
                data['default_rules'][dist] = []
            if desc_map.get(klass):
                data['default_rules'][dist].append({
                    'adverb': adverb,
                    'description': desc_map.get(klass)
                })

        add_stylesheet(req, 'announcer/css/announcer_prefs.css')
        if hasattr(Chrome(self.env), 'jenv'):
            return 'prefs_announcer_manage_subscriptions.html', dict(data=data), None
        else:
            return 'prefs_announcer_manage_subscriptions.html', dict(data=data)

    # ITemplateStreamFilter method

    def filter_stream(self, req, method, filename, stream, data):
        if re.match(r'/prefs/subscription', req.path_info):
            xpath_match = '//form[@id="userprefs"]//div[@class="buttons"]'
            stream |= Transformer(xpath_match).empty()
        return stream

    def _add_rule(self, arg, req):
        rule = Subscription(self.env)
        rule['sid'] = req.session.sid
        rule['authenticated'] = req.session.authenticated and 1 or 0
        rule['distributor'] = arg
        rule['format'] = req.args.get('format-%s' % arg, '')
        rule['adverb'] = req.args['new-adverb-%s' % arg]
        rule['class'] = req.args['new-rule-%s' % arg]
        Subscription.add(self.env, rule)

    def _delete_rule(self, arg, req):
        Subscription.delete(self.env, arg)

    def _move_rule(self, arg, req):
        (rule_id, new_priority) = arg.split('-')
        if int(new_priority) >= 1:
            Subscription.move(self.env, rule_id, int(new_priority))

    def _set_format(self, arg, req):
        Subscription.update_format_by_distributor_and_sid(
            self.env, arg, req.session.sid, req.session.authenticated,
            req.args['format-%s' % arg])
