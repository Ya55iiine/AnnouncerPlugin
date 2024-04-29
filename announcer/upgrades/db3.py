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
from trac.db.schema import Column, Table

schema = [
    Table('subscription', key='id')[
        Column('id', auto_increment=True),
        Column('time', type='int64'),
        Column('changetime', type='int64'),
        Column('class'),
        Column('sid'),
        Column('authenticated', type='int'),
        Column('distributor'),
        Column('format'),
        Column('priority'),
        Column('adverb')
    ],
    Table('subscription_attribute', key='id')[
        Column('id', auto_increment=True),
        Column('sid'),
        Column('class'),
        Column('name'),
        Column('value')
    ]
]


def do_upgrade(env, ver, cursor):
    """Add two more subscription db tables for a better normalized schema."""

    connector = DatabaseManager(env).get_connector()[0]
    for table in schema:
        for stmt in connector.to_sql(table):
            cursor.execute(stmt)
