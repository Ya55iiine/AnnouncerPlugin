# -*- coding: utf-8 -*-
#
# Copyright (c) 2008, Stephen Hansen
# Copyright (c) 2009, Robert Corsaro
# Copyright (c) 2012, Ryan J Ollos
# Copyright (c) 2012, Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import difflib

from jinja2 import Environment, FileSystemLoader
# from genshi.template import NewTextTemplate, MarkupTemplate, TemplateLoader
from trac.util.html import html
from trac.config import BoolOption, ListOption
from trac.core import implements
from trac.resource import Resource
from trac.test import Mock, MockPerm
from trac.ticket.api import TicketSystem
from trac.util import as_int
from trac.util.text import exception_to_unicode, to_unicode, wrap
from trac.versioncontrol.diff import unified_diff
from trac.web.chrome import Chrome, web_context
from trac.web.href import Href
from trac.wiki.formatter import HtmlFormatter
from trac.wiki.model import WikiPage

from announcer.api import _, IAnnouncementFormatter
from announcer.pref import AnnouncerTemplateProvider


def diff_cleanup(gen):
    for value in gen:
        if value.startswith('---'):
            continue
        if value.startswith('+++'):
            continue
        if value.startswith('@@'):
            yield '\n'
        else:
            yield value


def lineup(gen):
    for value in gen:
        yield ' ' + value


class TicketFormatter(AnnouncerTemplateProvider):

    implements(IAnnouncementFormatter)

    ticket_email_header_fields = ListOption('announcer',
        'ticket_email_header_fields',
        'owner, reporter, milestone, priority, severity',
        doc="""Comma-separated list of fields to appear in tickets. Use *
        to include all headers.
        """)

    ticket_link_with_comment = BoolOption('announcer',
        'ticket_link_with_comment', 'false',
        """Include last change anchor in the ticket URL.""")

    def styles(self, transport, realm):
        if realm == "ticket":
            yield "text/plain"
            yield "text/html"

    def alternative_style_for(self, transport, realm, style):
        if realm == "ticket" and style != 'text/plain':
            return "text/plain"

    def format(self, transport, realm, style, event):
        if realm == "ticket":
            if style == "text/plain":
                return self._format_plaintext(event)
            elif style == "text/html":
                return self._format_html(event)

    def _ticket_link(self, ticket):
        ticket_link = self.env.abs_href('ticket', ticket.id)
        if not self.ticket_link_with_comment:
            return ticket_link

        cnum = self._ticket_last_comment(ticket)
        if cnum is not None:
            ticket_link += "#comment:%s" % str(cnum)

        return ticket_link

    def _ticket_last_comment(self, ticket):
        cnum = -1

        for entry in ticket.get_changelog():
            (time, author, field, oldvalue, newvalue, permanent) = entry
            if field != 'comment':
                continue

            n = as_int(oldvalue, None)
            if n is None:
                continue

            if cnum < n:
                cnum = n

        if cnum == -1:
            return None
        else:
            return cnum

    def _format_plaintext(self, event):
        ticket = event.target
        short_changes = {}
        long_changes = {}
        changed_items = [(field, to_unicode(old_value))
                         for field, old_value in event.changes.items()]
        for field, old_value in changed_items:
            new_value = to_unicode(ticket[field])
            if '\n' in new_value or '\n' in old_value:
                long_changes[field.capitalize()] = \
                    '\n'.join(lineup(wrap(new_value, cols=67).split('\n')))
            else:
                short_changes[field.capitalize()] = (old_value, new_value)

        data = dict(
            ticket=ticket,
            author=event.author,
            comment=event.comment,
            fields=self._header_fields(ticket),
            category=event.category,
            ticket_link=self._ticket_link(ticket),
            project_name=self.env.project_name,
            project_desc=self.env.project_description,
            project_link=self.env.project_url or self.env.abs_href(),
            has_changes=short_changes or long_changes,
            long_changes=long_changes,
            short_changes=short_changes,
            attachment=event.attachment
        )
        # chrome = Chrome(self.env)
        # dirs = []
        # for provider in chrome.template_providers:
        #     dirs += provider.get_templates_dirs()
        # templates = TemplateLoader(dirs, variable_lookup='lenient')
        # template = templates.load('ticket_email_plaintext.txt',
        #                           cls=NewTextTemplate)
        # if template:
        #     stream = template.generate(**data)
        #     return stream.render('text')
        jinja_env = Environment(loader=FileSystemLoader('templates'))

        # Load your Jinja2 template
        template = jinja_env.get_template('ticket_email_plaintext.txt')

        # Render the template with context variables
        stream = template.render(**data)
        return stream

    def _header_fields(self, ticket):
        headers = self.ticket_email_header_fields
        fields = TicketSystem(self.env).get_ticket_fields()
        if len(headers) and headers[0].strip() != '*':
            def _filter(i):
                return i['name'] in headers

            fields = filter(_filter, fields)
        return fields

    def _format_html(self, event):
        ticket = event.target
        attachment = event.attachment
        short_changes = {}
        long_changes = {}
        for field, old_value in event.changes.items():
            new_value = ticket[field]
            if (new_value and '\n' in new_value) or \
                    (old_value and '\n' in old_value):
                long_changes[field.capitalize()] = html(
                    "<pre>\n%s\n</pre>" % (
                        '\n'.join(
                            diff_cleanup(
                                difflib.unified_diff(
                                    wrap(old_value, cols=60).split('\n'),
                                    wrap(new_value, cols=60).split('\n'),
                                    lineterm='', n=3
                                )
                            )
                        )
                    )
                )

            else:
                short_changes[field.capitalize()] = (old_value, new_value)

        def wiki_to_html(event, wikitext):
            if wikitext is None:
                return ""
            try:
                req = Mock(
                    href=Href(self.env.abs_href()),
                    abs_href=self.env.abs_href,
                    authname=event.author,
                    perm=MockPerm(),
                    chrome=dict(
                        warnings=[],
                        notices=[]
                    ),
                    args={}
                )
                resource = Resource(event.realm, event.target.id)
                context = web_context(req, resource)
                formatter = HtmlFormatter(self.env, context, wikitext)
                return formatter.generate(True)
            except Exception as e:
                self.log.error("Failed to render %s", repr(wikitext))
                self.log.error(exception_to_unicode(e, traceback=True))
                raise

        description = wiki_to_html(event, ticket['description'])

        if attachment:
            comment = wiki_to_html(event, attachment.description)
        else:
            comment = wiki_to_html(event, event.comment)

        data = dict(
            ticket=ticket,
            description=description,
            author=event.author,
            fields=self._header_fields(ticket),
            comment=comment,
            category=event.category,
            ticket_link=self._ticket_link(ticket),
            project_name=self.env.project_name,
            project_desc=self.env.project_description,
            project_link=self.env.project_url or self.env.abs_href(),
            has_changes=short_changes or long_changes,
            long_changes=long_changes,
            short_changes=short_changes,
            attachment=event.attachment,
            attachment_link=self.env.abs_href('attachment/ticket', ticket.id)
        )
        # Assuming you have Jinja2 templates in a directory 'path/to/templates'
        jinja_env = Environment(loader=FileSystemLoader('templates'))
        
        def render_template(template_name, data):
            template = jinja_env.get_template(template_name)
            return template.render(**data)
        
        # chrome = Chrome(self.env)
        # dirs = []
        # for provider in chrome.template_providers:
        #     dirs += provider.get_templates_dirs()
        # templates = TemplateLoader(dirs, variable_lookup='lenient')
        # template = templates.load('ticket_email_mimic.html',
        #                           cls=MarkupTemplate)
        # if template:
        #     stream = template.generate(**data)
        #     return stream.render()
        rendered_html = render_template('ticket_email_mimic.html', data)
        return rendered_html


class WikiFormatter(AnnouncerTemplateProvider):

    implements(IAnnouncementFormatter)

    wiki_email_diff = BoolOption('announcer', 'wiki_email_diff', 'true',
        """Should a wiki diff be sent with emails?""")

    def styles(self, transport, realm):
        if realm == 'wiki':
            yield 'text/plain'

    def alternative_style_for(self, transport, realm, style):
        if realm == 'wiki' and style != 'text/plain':
            return 'text/plain'

    def format(self, transport, realm, style, event):
        if realm == 'wiki' and style == 'text/plain':
            return self._format_plaintext(event)

    def _format_plaintext(self, event):
        page = event.target
        data = dict(
            action=event.category,
            attachment=event.attachment,
            page=page,
            author=event.author,
            comment=event.comment,
            category=event.category,
            page_link=self.env.abs_href('wiki', page.name),
            project_name=self.env.project_name,
            project_desc=self.env.project_description,
            project_link=self.env.project_url or self.env.abs_href(),
        )
        old_page = WikiPage(self.env, page.name, page.version - 1)
        if page.version:
            data['changed'] = True
            data['diff_link'] = self.env.abs_href('wiki', page.name,
                                                  action='diff',
                                                  version=page.version)
            if self.wiki_email_diff:
                # DEVEL: Formatter needs req object to get preferred language.
                diff_header = _("""
Index: %(name)s
==============================================================================
--- %(name)s (version: %(oldversion)s)
+++ %(name)s (version: %(version)s)
""")

                diff = "\n"
                diff += diff_header % {
                    'name': page.name,
                    'version': page.version,
                    'oldversion': page.version - 1
                }
                for line in unified_diff(old_page.text.splitlines(),
                                         page.text.splitlines(), context=3):
                    diff += "%s\n" % line
                data['diff'] = diff
        # chrome = Chrome(self.env)
        # dirs = []
        # for provider in chrome.template_providers:
        #     dirs += provider.get_templates_dirs()
        # templates = TemplateLoader(dirs, variable_lookup='lenient')
        # template = templates.load('wiki_email_plaintext.txt',
        #                           cls=NewTextTemplate)
        # if template:
        #     stream = template.generate(**data)
        #     return stream.render('text')
        # Create a Jinja2 environment
        jinja_env = Environment(loader=FileSystemLoader('templates'))

        # Load your Jinja2 template
        template = jinja_env.get_template('wiki_email_plaintext.txt')

        # Render the template with context variables
        stream = template.render(**data)
        return stream
