# -*- coding: utf-8 -*-
#
# Copyright (c) 2008, Stephen Hansen
# Copyright (c) 2009, Robert Corsaro
# Copyright (c) 2010,2012 Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

# TODO: pick format based on subscription.  For now users will use the same
#       format for all announcements, but in the future we can make this more
#       flexible, since it's in the subscription table.

import Queue
import hashlib
import random
import re
import threading
import time
from email.charset import Charset, QP, BASE64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, formataddr

from trac.config import BoolOption, ExtensionOption, Option, OrderedExtensionsOption
from trac.core import Component, ExtensionPoint, Interface, TracError, implements
from trac.notification.api import IEmailAddressResolver, IEmailSender
from trac.util.text import CRLF

from announcer.api import (
    _, IAnnouncementDistributor, IAnnouncementFormatter)
from announcer.model import Subscription
from announcer.util.mail import set_header
from announcer.util.mail_crypto import CryptoTxt


class IAnnouncementEmailDecorator(Interface):

    def decorate_message(event, message, decorators):
        """Manipulate the message before it is sent on it's way.  The callee
        should call the next decorator by popping decorators and calling the
        popped decorator.  If decorators is empty, don't worry about it.
        """


class EmailDistributor(Component):

    implements(IAnnouncementDistributor)

    formatters = ExtensionPoint(IAnnouncementFormatter)
    decorators = ExtensionPoint(IAnnouncementEmailDecorator)

    resolvers = OrderedExtensionsOption('announcer',
        'email_address_resolvers', IEmailAddressResolver,
        'SpecifiedEmailResolver, SessionEmailResolver, '
        'DefaultDomainEmailResolver',
        """Comma seperated list of email resolver components in the order
        they will be called.  If an email address is resolved, the remaining
        resolvers will not be called.
        """)

    email_sender = ExtensionOption('announcer', 'email_sender',
        IEmailSender, 'SmtpEmailSender',
        """Name of the component implementing `IEmailSender`.

        This component is used by the announcer system to send emails.
        Currently, `SmtpEmailSender` and `SendmailEmailSender` are provided.
        """)

    enabled = BoolOption('announcer', 'email_enabled', True,
        """Enable email notification.""")

    email_from = Option('announcer', 'email_from', 'trac@localhost',
        """Sender address to use in notification emails.""")

    from_name = Option('announcer', 'email_from_name', '',
        """Sender name to use in notification emails.""")

    reply_to = Option('announcer', 'email_replyto', 'trac@localhost',
        """Reply-To address to use in notification emails.""")

    mime_encoding = Option('announcer', 'mime_encoding', 'base64',
        """Specifies the MIME encoding scheme for emails.

        Valid options are 'base64' for Base64 encoding, 'qp' for
        Quoted-Printable, and 'none' for no encoding. Note that the no
        encoding means that non-ASCII characters in text are going to cause
        problems with notifications.
        """)

    use_public_cc = BoolOption('announcer', 'use_public_cc', 'false',
        """Recipients can see email addresses of other CC'ed recipients.

        If this option is disabled (the default), recipients are put on BCC
        """)

    # used in email decorators, but not here
    subject_prefix = Option('announcer', 'email_subject_prefix',
        '__default__',
        """Text to prepend to subject line of notification emails.

        If the setting is not defined, then the [$project_name] prefix.
        If no prefix is desired, then specifying an empty option
        will disable it.
        """)

    to_default = 'undisclosed-recipients: ;'
    to = Option('announcer', 'email_to', to_default, 'Default To: field')

    use_threaded_delivery = BoolOption('announcer', 'use_threaded_delivery',
        False,
        """Do message delivery in a separate thread.

        Enabling this will improve responsiveness for requests that end up
        with an announcement being sent over email. It requires building
        Python with threading support enabled-- which is usually the case.
        To test, start Python and type 'import threading' to see
        if it raises an error.
        """)

    default_email_format = Option('announcer', 'default_email_format',
        'text/plain',
        """The default mime type of the email notifications.

        This can be overridden on a per user basis through the announcer
        preferences panel.
        """)

    rcpt_allow_regexp = Option('announcer', 'rcpt_allow_regexp', '',
        """A whitelist pattern to match any address to before adding to
        recipients list.
        """)

    rcpt_local_regexp = Option('announcer', 'rcpt_local_regexp', '',
        """A whitelist pattern to match any address, that should be
        considered local.

        This will be evaluated only if msg encryption is set too.
        Recipients with matching email addresses will continue to
        receive unencrypted email messages.
        """)

    crypto = Option('announcer', 'email_crypto', '',
        """Enable cryptographically operation on email msg body.

        Empty string, the default for unset, disables all crypto operations.
        Valid values are:
            sign          sign msg body with given privkey
            encrypt       encrypt msg body with pubkeys of all recipients
            sign,encrypt  sign, than encrypt msg body
        """)

    # get GnuPG configuration options
    gpg_binary = Option('announcer', 'gpg_binary', 'gpg',
        """GnuPG binary name, allows for full path too.

        Value 'gpg' is same default as in python-gnupg itself.
        For usual installations location of the gpg binary is auto-detected.
        """)

    gpg_home = Option('announcer', 'gpg_home', '',
        """Directory containing keyring files.

        In case of wrong configuration missing keyring files without content
        will be created in the configured location, provided necessary
        write permssion is granted for the corresponding parent directory.
        """)

    private_key = Option('announcer', 'gpg_signing_key', None,
         """Keyid of private key (last 8 chars or more) used for signing.

         If unset, a private key will be selected from keyring automagicly.
         The password must be available i.e. provided by running gpg-agent
         or empty (bad security). On failing to unlock the private key,
         msg body will get emptied.
         """)

    def __init__(self):
        self.enigma = None
        self.delivery_queue = None
        self._init_pref_encoding()

    def get_delivery_queue(self):
        if not self.delivery_queue:
            self.delivery_queue = Queue.Queue()
            thread = DeliveryThread(self.delivery_queue, self.send)
            thread.start()
        return self.delivery_queue

    # IAnnouncementDistributor methods

    def transports(self):
        yield 'email'

    def formats(self, transport, realm):
        """Find valid formats for transport and realm."""
        formats = {}
        for f in self.formatters:
            for style in f.styles(transport, realm):
                formats[style] = f
        self.log.debug("EmailDistributor has found the following formats "
                       "capable of handling '%s' of '%s': %s",
                       transport, realm, ', '.join(formats.keys()))
        if not formats:
            self.log.error("EmailDistributor is unable to continue without "
                           "supporting formatters.")
        return formats

    def distribute(self, transport, recipients, event):
        found = False
        for supported_transport in self.transports():
            if supported_transport == transport:
                found = True
        if not self.enabled or not found:
            self.log.debug("EmailDistributor email_enabled set to false")
            return
        formats = self.formats(transport, event.realm)
        if not formats:
            self.log.error("EmailDistributor No formats found for %s %s",
                           transport, event.realm)
            return
        msgdict = {}
        msgdict_encrypt = {}
        msg_pubkey_ids = []
        # compile pattern before use for better performance
        rcpt_allow_re = re.compile(self.rcpt_allow_regexp)
        rcpt_local_re = re.compile(self.rcpt_local_regexp)

        if self.crypto != '':
            self.log.debug("EmailDistributor attempts crypto operation.")
            self.enigma = CryptoTxt(self.gpg_binary, self.gpg_home)

        for name, authed, address in recipients:
            fmt = name and \
                  self._get_preferred_format(event.realm, name, authed) or \
                  self._get_default_format()
            old_fmt = fmt
            if fmt not in formats:
                self.log.debug("EmailDistributor format %s not available "
                               "for %s %s, looking for an alternative",
                               fmt, transport, event.realm)
                # If the fmt is not available for this realm, then try to find
                # an alternative
                fmt = None
                for f in formats.values():
                    fmt = f.alternative_style_for(
                        transport, event.realm, old_fmt)
                    if fmt:
                        break
            if not fmt:
                self.log.error("EmailDistributor was unable to find a "
                               "formatter for format %s", old_fmt)
                continue
            resolver = None
            if name and not address:
                # figure out what the addr should be if it's not defined
                for resolver in self.resolvers:
                    address = resolver.get_address_for_session(name, authed)
                    if address:
                        break
            if address:
                self.log.debug("EmailDistributor found the address '%s' "
                               "for '%s (%s)' via: %s", address, name,
                               authed and 'authenticated' or
                               'not authenticated',
                               resolver.__class__.__name__)

                # ok, we found an addr, add the message
                # but wait, check for allowed rcpt first, if set
                if rcpt_allow_re.search(address) is not None:
                    # check for local recipients now
                    local_match = rcpt_local_re.search(address)
                    if self.crypto in ['encrypt', 'sign,encrypt'] and \
                            local_match is None:
                        # search available public keys for matching UID
                        pubkey_ids = self.enigma.get_pubkey_ids(address)
                        if pubkey_ids > 0:
                            msgdict_encrypt.setdefault(fmt, set())\
                                .add((name, authed, address))
                            msg_pubkey_ids[len(msg_pubkey_ids):] = pubkey_ids
                            self.log.debug("EmailDistributor got pubkeys "
                                           "for %s: %s", address, pubkey_ids)
                        else:
                            self.log.debug("EmailDistributor dropped %s "
                                           "after missing pubkey with "
                                           "corresponding address %s in any "
                                           "UID", name, address)
                    else:
                        msgdict.setdefault(fmt, set())\
                            .add((name, authed, address))
                        if local_match is not None:
                            self.log.debug("EmailDistributor expected local "
                                           "delivery for %s to: %s", name,
                                           address)
                else:
                    self.log.debug("EmailDistributor dropped %s for not "
                                   "matching allowed recipient pattern %s",
                                   address, self.rcpt_allow_regexp)
            else:
                self.log.debug("EmailDistributor was unable to find an "
                               "address for: %s (%s)", name, authed and
                               'authenticated' or 'not authenticated')
        for k, v in msgdict.items():
            if not v or not formats.get(k):
                continue
            fmt = formats[k]
            self.log.debug("EmailDistributor is sending event as '%s' to: "
                           "%s", fmt, ', '.join(x[2] for x in v))
            self._do_send(transport, event, k, v, fmt)
        for k, v in msgdict_encrypt.items():
            if not v or not formats.get(k):
                continue
            fmt = formats[k]
            self.log.debug("EmailDistributor is sending encrypted info on "
                           "event as '%s' to: %s", fmt,
                           ', '.join(x[2] for x in v))
            self._do_send(transport, event, k, v, formats[k], msg_pubkey_ids)

    def _get_default_format(self):
        return self.default_email_format

    def _get_preferred_format(self, realm, sid, authenticated):
        if authenticated is None:
            authenticated = 0
        # Format is unified for all subscriptions of a user.
        result = Subscription.find_by_sid_and_distributor(
            self.env, sid, authenticated, 'email')
        if result:
            chosen = result[0]['format']
            self.log.debug("EmailDistributor determined the preferred format"
                           " for '%s (%s)' is: %s", sid, authenticated and
                           'authenticated' or 'not authenticated', chosen)
            return chosen
        else:
            return self._get_default_format()

    def _init_pref_encoding(self):
        self._charset = Charset()
        self._charset.input_charset = 'utf-8'
        pref = self.mime_encoding.lower()
        if pref == 'base64':
            self._charset.header_encoding = BASE64
            self._charset.body_encoding = BASE64
            self._charset.output_charset = 'utf-8'
            self._charset.input_codec = 'utf-8'
            self._charset.output_codec = 'utf-8'
        elif pref in ['qp', 'quoted-printable']:
            self._charset.header_encoding = QP
            self._charset.body_encoding = QP
            self._charset.output_charset = 'utf-8'
            self._charset.input_codec = 'utf-8'
            self._charset.output_codec = 'utf-8'
        elif pref == 'none':
            self._charset.header_encoding = None
            self._charset.body_encoding = None
            self._charset.input_codec = None
            self._charset.output_charset = 'ascii'
        else:
            raise TracError(_("Invalid email encoding setting: %(pref)s",
                              pref=pref))

    def _message_id(self, realm):
        """Generate a predictable, but sufficiently unique message ID."""
        modtime = time.time()
        rand = random.randint(0, 32000)
        s = '%s.%d.%d.%s' % (self.env.project_url,
                             modtime, rand,
                             realm.encode('ascii', 'ignore'))
        dig = hashlib.md5(s).hexdigest()
        host = self.email_from[self.email_from.find('@') + 1:]
        msgid = '<%03d.%s@%s>' % (len(s), dig, host)
        return msgid

    def _filter_recipients(self, rcpt):
        return rcpt

    def _do_send(self, transport, event, format, recipients, formatter,
                 pubkey_ids=None):
        pubkey_ids = pubkey_ids or []
        # Prepare sender for use in IEmailSender component and message header.
        from_header = formataddr(
            (self.from_name and self.from_name or self.env.project_name,
             self.email_from)
        )
        headers = dict()
        headers['Message-ID'] = self._message_id(event.realm)
        headers['Date'] = formatdate()
        headers['From'] = from_header
        headers['Reply-To'] = self.reply_to

        recip_adds = [x[2] for x in recipients if x]

        if self.use_public_cc:
            headers['Cc'] = ', '.join(recip_adds)
        else:
            # Use localized Bcc: hint for default To: content.
            if self.to == self.to_default:
                headers['To'] = _("undisclosed-recipients: ;")
            else:
                headers['To'] = '"%s"' % self.to
                if self.to:
                    recip_adds += [self.to]
        if not recip_adds:
            self.log.debug("EmailDistributor stopped (no recipients).")
            return
        self.log.debug("All email recipients: %s", recip_adds)

        root_message = MIMEMultipart('related')

        # Write header data into message object.
        for k, v in headers.iteritems():
            set_header(root_message, k, v)

        output = formatter.format(transport, event.realm, format, event)

        # DEVEL: Currently crypto operations work with format text/plain only.
        alternate_output = None
        alternate_style = []
        if self.crypto != '' and pubkey_ids:
            if self.crypto == 'sign':
                output = self.enigma.sign(output, self.private_key)
            elif self.crypto == 'encrypt':
                output = self.enigma.encrypt(output, pubkey_ids)
            elif self.crypto == 'sign,encrypt':
                output = self.enigma.sign_encrypt(output, pubkey_ids,
                                                  self.private_key)
            self.log.debug(output)
            self.log.debug("EmailDistributor crypto operation successful.")
        else:
            alternate_style = formatter.alternative_style_for(
                transport,
                event.realm,
                format
            )
            if alternate_style:
                alternate_output = formatter.format(
                    transport,
                    event.realm,
                    alternate_style,
                    event
                )

        # Sanity check for suitable encoding setting.
        if not self._charset.body_encoding:
            try:
                output.encode('ascii')
            except UnicodeDecodeError:
                raise TracError(_("Ticket contains non-ASCII chars. Please "
                                  "change encoding setting"))

        root_message.preamble = "This is a multi-part message in MIME format."
        if alternate_output:
            parent_message = MIMEMultipart('alternative')
            root_message.attach(parent_message)

            alt_msg_format = 'html' in alternate_style and 'html' or 'plain'
            if isinstance(alternate_output, str):
                alternate_output = alternate_output.encode('utf-8')
            msg_text = MIMEText(alternate_output, alt_msg_format)
            msg_text.set_charset(self._charset)
            parent_message.attach(msg_text)
        else:
            parent_message = root_message

        msg_format = 'html' in format and 'html' or 'plain'
        if isinstance(output, str):
            output = output.encode('utf-8')
        msg_text = MIMEText(output, msg_format)
        del msg_text['Content-Transfer-Encoding']
        msg_text.set_charset(self._charset)
        # According to RFC 2046, the last part of a multipart message is best
        #   and preferred.
        parent_message.attach(msg_text)

        # DEVEL: Decorators can interfere with crypto operation here. Fix it.
        decorators = self._get_decorators()
        if decorators:
            decorator = decorators.pop()
            decorator.decorate_message(event, root_message, decorators)

        package = (from_header, recip_adds, root_message.as_string())
        start = time.time()
        if self.use_threaded_delivery:
            self.get_delivery_queue().put(package)
        else:
            self.send(*package)
        stop = time.time()
        self.log.debug("EmailDistributor took %s seconds to send.",
                       round(stop - start, 2))

    def send(self, from_addr, recipients, message):
        """Send message to recipients via e-mail."""
        # Ensure the message complies with RFC2822: use CRLF line endings
        message = CRLF.join(re.split('\r?\n', message))
        self.email_sender.send(from_addr, recipients, message)

    def _get_decorators(self):
        return self.decorators[:]


class DeliveryThread(threading.Thread):
    def __init__(self, queue, sender):
        threading.Thread.__init__(self)
        self._sender = sender
        self._queue = queue
        self.setDaemon(True)

    def run(self):
        while 1:
            send_from, recipients, message = self._queue.get()
            self._sender(send_from, recipients, message)
