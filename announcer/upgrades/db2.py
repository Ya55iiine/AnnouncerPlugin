# -*- coding: utf-8 -*-
#
# Copyright (c) 2008, Stephen Hansen
# Copyright (c) 2009, Robert Corsaro
# Copyright (c) 2010-2012, Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from trac.db.api import DatabaseManager
from trac.db.schema import Column, Index, Table

schema = [
    Table('subscriptions', key='id')[
        Column('id', auto_increment=True),
        Column('sid'),
        Column('authenticated', type='int'),
        Column('enabled', type='int'),
        Column('managed'),
        Column('realm'),
        Column('category'),
        Column('rule'),
        Column('transport'),
        Index(['id']),
        Index(['realm', 'category', 'enabled']),
    ]
]


def do_upgrade(env, ver, cursor):
    """Changes to subscription db table:

    - 'subscriptions.destination', 'subscriptions.format'
    + 'subscriptions.authenticated', 'subscriptions.transport'
    'subscriptions.managed' type='int' --> (default == char)
    """
    cursor.execute("""
        CREATE TEMPORARY TABLE subscriptions_old
            AS SELECT * FROM subscriptions
    """)
    cursor.execute("DROP TABLE subscriptions")

    connector = DatabaseManager(env).get_connector()[0]
    for table in schema:
        for stmt in connector.to_sql(table):
            cursor.execute(stmt)
    cursor.execute("""
        INSERT INTO subscriptions
               (sid,authenticated,enabled,managed,
                realm,category,rule,transport)
        SELECT o.sid,s.authenticated,o.enabled,'watcher',
               o.realm,o.category,rule,'email'
          FROM subscriptions_old AS o
          LEFT JOIN session AS s
               ON o.sid=s.sid
    """)
    cursor.execute("DROP TABLE subscriptions_old")
