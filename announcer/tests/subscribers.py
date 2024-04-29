# -*- coding: utf-8 -*-
#
# Copyright (c) 2012, Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.db.api import DatabaseManager
from trac.test import EnvironmentStub

from announcer.subscribers import CarbonCopySubscriber, \
                                  TicketOwnerSubscriber, \
                                  TicketReporterSubscriber, \
                                  TicketUpdaterSubscriber


class SubscriberTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(
            enable=['trac.*', 'announcer.subscribers.*'])
        self.env.path = tempfile.mkdtemp()
        self.db_mgr = DatabaseManager(self.env)

    def tearDown(self):
        self.env.shutdown()
        shutil.rmtree(self.env.path)


class CarbonCopySubscriberTestCase(SubscriberTestCase):

    def test_init(self):
        # Test just to confirm that CarbonCopySubscriber initializes cleanly.
        CarbonCopySubscriber(self.env)
        pass


class TicketOwnerSubscriberTestCase(SubscriberTestCase):

    def test_init(self):
        # Test just to confirm that TicketOwnerSubscriber initializes cleanly.
        TicketOwnerSubscriber(self.env)
        pass


class TicketReporterSubscriberTestCase(SubscriberTestCase):

    def test_init(self):
        # Test just to confirm that TicketReporterSubscriber initializes
        #   cleanly.
        TicketReporterSubscriber(self.env)
        pass


class TicketUpdaterSubscriberTestCase(SubscriberTestCase):

    def test_init(self):
        # Test just to confirm that TicketUpdaterSubscriber initializes
        #   cleanly.
        TicketUpdaterSubscriber(self.env)
        pass


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(CarbonCopySubscriberTestCase))
    suite.addTest(unittest.makeSuite(TicketOwnerSubscriberTestCase))
    suite.addTest(unittest.makeSuite(TicketReporterSubscriberTestCase))
    suite.addTest(unittest.makeSuite(TicketUpdaterSubscriberTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
