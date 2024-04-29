# -*- coding: utf-8 -*-
#
# Copyright (c) 2010, Robert Corsaro
# Copyright (c) 2010, Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from bitten.api import IBuildListener
from bitten.model import Build, BuildStep, BuildLog
from genshi.template import NewTextTemplate, TemplateLoader
from trac.core import Component, implements
from trac.web.chrome import Chrome

from announcer.api import _, AnnouncementSystem, AnnouncementEvent, \
                          IAnnouncementFormatter, IAnnouncementSubscriber, \
                          IAnnouncementPreferenceProvider
from announcer.distributors.mail import IAnnouncementEmailDecorator
from announcer.util.mail import set_header, next_decorator
from announcer.util.settings import BoolSubscriptionSetting


class BittenAnnouncedEvent(AnnouncementEvent):
    def __init__(self, build, category):
        AnnouncementEvent.__init__(self, 'bitten', category, build)


class BittenAnnouncement(Component):
    """Send announcements on build status."""

    implements(IAnnouncementEmailDecorator, IAnnouncementFormatter,
               IAnnouncementPreferenceProvider, IAnnouncementSubscriber,
               IBuildListener)

    readable_states = {
        Build.SUCCESS: _("Successful"),
        Build.FAILURE: _("Failed"),
    }

    # IBuildListener methods

    def build_started(self, build):
        """build started"""
        self._notify(build, 'started')

    def build_aborted(self, build):
        """build aborted"""
        self._notify(build, 'aborted')

    def build_completed(self, build):
        """build completed"""
        self._notify(build, 'completed')

    # IAnnouncementSubscriber methods

    def subscriptions(self, event):
        if event.realm == 'bitten':
            settings = self._settings()
            if event.category in settings.keys():
                for subscriber in \
                        settings[event.category].get_subscriptions():
                    self.log.debug("BittenAnnouncementSubscriber added '%s "
                                   "(%s)'", subscriber[1], subscriber[2])
                    yield subscriber

    def matches(self, event):
        yield None

    def description(self):
        return _("notify me bitten changes NOT IMPLEMENTED")

    # IAnnouncementFormatter methods

    def styles(self, transport, realm):
        if realm == 'bitten':
            yield 'text/plain'

    def alternative_style_for(self, transport, realm, style):
        if realm == 'bitten' and style != 'text/plain':
            return 'text/plain'

    def format(self, transport, realm, style, event):
        if realm == 'bitten' and style == 'text/plain':
            return self._format_plaintext(event)

    # IAnnouncementEmailDecorator methods

    def decorate_message(self, event, message, decorates=None):
        if event.realm == "bitten":
            build_id = str(event.target.id)
            build_link = self._build_link(event.target)
            subject = '[%s Build] %s [%s] %s' % (
                self.readable_states.get(
                    event.target.status,
                    event.target.status
                ),
                self.env.project_name,
                event.target.rev,
                event.target.config
            )
            set_header(message, 'X-Trac-Build-ID', build_id)
            set_header(message, 'X-Trac-Build-URL', build_link)
            set_header(message, 'Subject', subject)
        return next_decorator(event, message, decorates)

    # IAnnouncementPreferenceProvider methods

    def get_announcement_preference_boxes(self, req):
        if req.authname == 'anonymous' and 'email' not in req.session:
            return
        yield 'bitten_subscription', _("Bitten Subscription")

    def render_announcement_preference_box(self, req, panel):
        settings = self._settings()
        if req.method == 'POST':
            for k, setting in settings.items():
                setting.set_user_setting(req.session,
                                         value=req.args.get(
                                             'bitten_%s_subscription' % k),
                                         save=False)
            req.session.save()
        data = {}
        for k, setting in settings.items():
            data[k] = setting.get_user_setting(req.session.sid)[1]
        return 'prefs_announcer_bitten.html', data

    # Private methods

    def _notify(self, build, category):
        self.log.info("BittenAnnouncedEventProducer invoked for build %r",
                      build)
        self.log.debug("build status: %s", build.status)
        self.log.info("Creating announcement for build %s", build)
        announcer = AnnouncementSystem(self.env)
        try:
            announcer.send(BittenAnnouncedEvent(build, category))
        except Exception, e:
            self.log.exception("Failure creating announcement for build "
                               "%s: %s", build.id, e)

    def _settings(self):
        ret = {}
        for p in ('started', 'aborted', 'completed'):
            ret[p] = BoolSubscriptionSetting(self.env, 'bitten_%s' % p)
        return ret

    def _format_plaintext(self, event):
        failed_steps = BuildStep.select(self.env, build=event.target.id,
                                        status=BuildStep.FAILURE)
        change = self._get_changeset(event.target)
        data = {
            'build': {
                'id': event.target.id,
                'status': self.readable_states.get(
                    event.target.status, event.target.status
                ),
                'link': self._build_link(event.target),
                'config': event.target.config,
                'slave': event.target.slave,
                'failed_steps': [{
                    'name': step.name,
                    'description': step.description,
                    'errors': step.errors,
                    'log_messages':
                        self._get_all_log_messages_for_step(event.target,
                                                            step),
                } for step in failed_steps],
            },
            'change': {
                'rev': change.rev,
                'link': self.env.abs_href.changeset(change.rev),
                'author': change.author,
            },
            'project': {
                'name': self.env.project_name,
                'url': self.env.project_url or self.env.abs_href(),
                'descr': self.env.project_description
            }
        }
        chrome = Chrome(self.env)
        dirs = []
        for provider in chrome.template_providers:
            dirs += provider.get_templates_dirs()
        templates = TemplateLoader(dirs, variable_lookup='lenient')
        template = templates.load('bitten_plaintext.txt',
                                  cls=NewTextTemplate)
        if template:
            stream = template.generate(**data)
            return stream.render('text')

    def _build_link(self, build):
        return self.env.abs_href.build(build.config, build.id)

    def _get_all_log_messages_for_step(self, build, step):
        messages = []
        for log in BuildLog.select(self.env, build=build.id,
                                   step=step.name):
            messages.extend(log.messages)
        return messages

    def _get_changeset(self, build):
        return self.env.get_repository().get_changeset(build.rev)
