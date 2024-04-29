# -*- coding: utf-8 -*-
#
# Copyright (c) 2009, Robert Corsaro
# Copyright (c) 2012, Steffen Hoffmann
# Copyright (c) 2012, Ryan J Ollos
# Copyright (c) 2012, Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest
from pkg_resources import resource_filename

from trac.attachment import Attachment
from trac.test import EnvironmentStub
from trac.ticket.model import Ticket
from trac.web.chrome import Chrome

from announcer.formatters import TicketFormatter, WikiFormatter
from announcer.producers import TicketChangeEvent


class FormatterTestCase(unittest.TestCase):
    def setUp(self):
        self.env = EnvironmentStub(
            enable=['trac.*', 'announcer.formatters.*'])
        self.env.path = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.env.path)


class TicketFormatterTestCase(FormatterTestCase):
    def setUp(self):
        FormatterTestCase.setUp(self)
        self.tf = TicketFormatter(self.env)

    def test_styles(self):
        self.assertTrue('text/html' in self.tf.styles('email', 'ticket'))
        self.assertTrue('text/plain' in self.tf.styles('email', 'ticket'))
        self.assertFalse('text/plain' in self.tf.styles('email', 'wiki'))
        self.assertEqual('text/plain',
                         self.tf.alternative_style_for('email', 'ticket',
                                                       'text/blah'))
        self.assertEqual('text/plain',
                         self.tf.alternative_style_for('email', 'ticket',
                                                       'text/html'))
        self.assertEqual(None,
                         self.tf.alternative_style_for('email', 'ticket',
                                                       'text/plain'))

    def test_template_dirs_added(self):
        self.assertTrue(self.tf in Chrome(self.env).template_providers)


class WikiFormatterTestCase(FormatterTestCase):
    def setUp(self):
        FormatterTestCase.setUp(self)
        self.wf = WikiFormatter(self.env)

    def test_styles(self):
        # HTML format for email notifications is yet unsupported for wiki.
        # self.assertTrue('text/html' in self.tf.styles('email', 'wiki'))
        self.assertTrue('text/plain' in self.wf.styles('email', 'wiki'))
        self.assertFalse('text/plain' in self.wf.styles('email', 'ticket'))
        self.assertEqual('text/plain',
                         self.wf.alternative_style_for('email', 'wiki',
                                                       'text/blah'))
        self.assertEqual('text/plain',
                         self.wf.alternative_style_for('email', 'wiki',
                                                       'text/html'))
        self.assertEqual(None,
                         self.wf.alternative_style_for('email', 'wiki',
                                                       'text/plain'))

    def test_template_dirs_added(self):
        self.assertTrue(self.wf in Chrome(self.env).template_providers)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TicketFormatterTestCase))
    suite.addTest(unittest.makeSuite(WikiFormatterTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
