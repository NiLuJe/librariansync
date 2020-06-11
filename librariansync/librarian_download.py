#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

# requires librarian_download.ini
#
# [server]
# IP = 192.168.1.5|192.168.15.201
# port = 13698
#

from __future__ import absolute_import

import requests
import os
import time
import sys
import sqlite3
import six.moves.configparser
from kindle_logging import log, LIBRARIAN_SYNC
from generate_collections import update_cc_db, KINDLE_DB_PATH

ebook_mimetypes = ['application/epub+zip', 'application/x-mobipocket-ebook']

DESTINATION_DIR = u'/mnt/us/documents/library/'
COLLECTIONS_DIR = u'/mnt/us/extensions'
SERVER_HTTP = u"http://%s:%s/"


def url(ip, port, arg):
    return os.path.join(SERVER_HTTP % (ip, port), arg)


def download_file(ip, port, url):
    r = requests.get(url, stream=True)

    if r.headers['content-type'] in ebook_mimetypes or\
       r.headers['content-type'] == "application/json":

        filename = url.split(SERVER_HTTP % (ip, port))[1]
        if filename == "collections.json":
            local_filename = os.path.join(COLLECTIONS_DIR, filename)
        else:
            local_filename = os.path.join(DESTINATION_DIR, filename)
        if not os.path.exists(os.path.dirname(local_filename)):
            log(LIBRARIAN_SYNC, u"download_file",
                u"Creating %s" % os.path.dirname(local_filename))
            os.makedirs(os.path.dirname(local_filename))
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)
                    f.flush()
        return r.status_code, r.headers['content-type'], local_filename
    elif r.headers['content-type'] == "text/plain":
        r.encoding = "utf8"
        return r.status_code, r.headers['content-type'], r.text
    else:
        return r.status_code, r.headers['content-type'], None


def download_all_served_ebooks(ip, port):
    # ask for available ebooks
    code, mimetype, result = download_file(ip, port, url(ip, port, "index"))
    if code == requests.codes.ok and mimetype == "text/plain":
        epubs = result.split("|")
        # download them all
        for epub in epubs:
            log(LIBRARIAN_SYNC, u"download",
                u"D/L: %s." % os.path.basename(epub))
            code, mimetype, result = download_file(ip, port,
                                                   url(ip, port, epub))
            if code == requests.codes.not_found:
                log(LIBRARIAN_SYNC, u"download", u"%s not found." % epub, u"W")
            elif code == requests.codes.ok:
                if mimetype not in ebook_mimetypes:
                    raise Exception("what?")
                else:
                    log(LIBRARIAN_SYNC, u"download",
                        u"Downloaded: %s." % os.path.basename(epub),
                        display=False)
        # ask for the associated collections
        code, mimetype, result = download_file(ip, port,
                                               url(ip, port,
                                                   "collections.json"))
        # shutdown the server, all done
        code, mimetype, result = download_file(ip, port,
                                               url(ip, port,
                                                   "LibrarianServer::shutdown")
                                               )
        if code == requests.codes.ok and mimetype == "text/plain":
            log(LIBRARIAN_SYNC, u"shutdown", result)
    else:
        log(LIBRARIAN_SYNC, u"retrieve_index", u"Could not retrieve index.")


if __name__ == "__main__":
    start = time.time()
    log(LIBRARIAN_SYNC, u"download", u"Starting...")
    try:
        config = six.moves.configparser.ConfigParser()
        config.read("librarian_download.ini")
        IPs = config.get("server", "IP", "localhost").split("|")
        port = config.get("server", "port", 13699)
    except:
        log(LIBRARIAN_SYNC, u"download",
            u"Missing or incorrect configuration file.")
    failed = 0
    for ip in IPs:
        try:
            download_all_served_ebooks(ip, port)
        except requests.packages.urllib3.exceptions.ProtocolError as e:
            err, code = e
            failed += 1
            log(LIBRARIAN_SYNC, u"connect", u"%s : %s" % (ip, code),
                display=False)

    if failed == len(IPs):
        log(LIBRARIAN_SYNC, u"connect",
            u"Impossible to connect to librarian.", "E")
    else:
        # update collections
        try:
            with sqlite3.connect(KINDLE_DB_PATH) as cc_db:
                c = cc_db.cursor()
                log(LIBRARIAN_SYNC, u"update", u"Updating collections...")
                update_cc_db(c, complete_rebuild=False, source="librarian")
        except:
            log(LIBRARIAN_SYNC, u"main",
                u"Something went wrong while updating collections.", u"E")

        log(LIBRARIAN_SYNC, u"download",
            u"Done in %.02fs." % (time.time()-start))
        # Take care of buffered IO & KUAL's IO redirection...
        sys.stdout.flush()
        sys.stderr.flush()
