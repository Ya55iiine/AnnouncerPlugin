# -*- coding: utf-8 -*-
#
# Copyright (c) 2010, Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re
import time

try:
    from gnupg import GPG
except ImportError:
    GPG = None
from trac.core import TracError
from trac.util.translation import _


class CryptoTxt:
    """Crypto operation provider for plaintext.

    We use GnuPG for now. Support for X.509 and other options might
    appear in the future.
    """

    def __init__(self, gpg_binary, gpg_home):
        """Initialize the GnuPG instance."""

        self.gpg_binary = gpg_binary
        self.gpg_home = gpg_home
        if not GPG:
            raise TracError(_("Unable to load the python-gnupg module. "
                              "Please check and correct your installation."))
        try:
            self.gpg = GPG(gpgbinary=self.gpg_binary, gnupghome=self.gpg_home)
        except ValueError:
            raise TracError(_("Missing the crypto binary. Please check and "
                              "set full path with option 'gpg_binary'."))
        else:
            # get list of available public keys once for later use
            self.pub_keys = self.gpg.list_keys()

    def sign(self, content, private_key=None):
        private_key = self._get_private_key(private_key)

        cipher = self.gpg.sign(content, keyid=private_key, passphrase='')
        return str(cipher)

    def encrypt(self, content, pubkeys):
        # always_trust needed for making it work with just any pubkey
        cipher = self.gpg.encrypt(content, pubkeys, always_trust=True)
        return str(cipher)

    def sign_encrypt(self, content, pubkeys, private_key=None):
        private_key = self._get_private_key(private_key)

        # always_trust needed for making it work with just any pubkey
        cipher = self.gpg.encrypt(content, pubkeys, always_trust=True,
                                  sign=private_key, passphrase='')
        return str(cipher)

    def get_pubkey_ids(self, addr):
        """Find public key with UID matching address to encrypt to."""

        pubkey_ids = []
        if self.pub_keys and 'uids' in self.pub_keys[-1] and \
                'fingerprint' in self.pub_keys[-1]:
            # compile pattern before use for better performance
            rcpt_re = re.compile(addr)
            for k in self.pub_keys:
                for uid in k['uids']:
                    match = rcpt_re.search(uid)
                    if match is not None:
                        # check for key expiration
                        if k['expires'] == '':
                            pubkey_ids.append(k['fingerprint'][-16:])
                        elif (time.time() + 60) < float(k['expires']):
                            pubkey_ids.append(k['fingerprint'][-16:])
                        break
        return pubkey_ids

    def _get_private_key(self, privkey=None):
        """Find private (secret) key to sign with."""

        # read private keys from keyring
        privkeys = self.gpg.list_keys(True)  # True => private keys
        if privkeys > 0 and 'fingerprint' in privkeys[-1]:
            fingerprints = []
            for k in privkeys:
                fingerprints.append(k['fingerprint'])
        else:
            # no private key in keyring
            return None

        if privkey:
            # check for existence of private key received as argument
            # DEVEL: check for expiration as well
            if 7 < len(privkey) <= 40:
                for fp in fingerprints:
                    if fp.endswith(privkey):
                        # work with last 16 significant chars internally,
                        # even if only 8 are required in trac.ini
                        privkey = fp[-16:]
                        break
                # no fingerprint matching key ID
                else:
                    privkey = None
            else:
                # reset invalid key ID
                privkey = None
        else:
            # select (last) private key from keyring
            privkey = fingerprints[-1][-16:]

        return privkey
