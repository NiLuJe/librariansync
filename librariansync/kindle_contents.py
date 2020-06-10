from __future__ import absolute_import

import os
import re
import locale
import time

from kindle_logging import log, LIBRARIAN_SYNC

KINDLE_EBOOKS_ROOT = "/mnt/us/documents/"

SUPPORTED_EXTENSIONS = [".azw",
                        ".mobi",
                        ".prc",
                        ".pobi",
                        ".azw3",
                        ".azw6",
                        ".yj",
                        ".azw1",
                        ".tpz",
                        ".pdf",
                        ".txt",
                        ".html",
                        ".htm",
                        ".jpg",
                        ".jpeg",
                        ".azw2",
                        ".kfx",
                        ".epub"]


# -------- Folders
def list_folder_contents():
    folder_contents = {}
    for root, dirs, files in os.walk(KINDLE_EBOOKS_ROOT):
        for f in [get_relative_path(os.path.join(root, el))
                  for el in files
                  if os.path.splitext(el.lower())[1] in SUPPORTED_EXTENSIONS]:
            # if not directly in KINDLE_EBOOKS_ROOT
            if get_relative_path(root) != u"":
                folder_contents[f] = [get_relative_path(root)]
    return folder_contents


def get_relative_path(path):
    if isinstance(path, str):
        return path.split(KINDLE_EBOOKS_ROOT)[1].decode("utf8")
    else:
        return path.split(KINDLE_EBOOKS_ROOT)[1]


# -------- Ebooks and Collections
class Ebook(object):
    def __init__(self, uuid, location, cdekey, cdetype):
        self.uuid = uuid
        self.location = location
        self.cdekey = cdekey
        self.cdetype = cdetype
        self.original_collections = []
        self.collections = []

    def __eq__(self, other):
        # comparing uuids should be enough
        return self.uuid == other.uuid

    def add_collection(self, collection, original=False):
        if original:
            self.original_collections.append(collection)
        else:
            self.collections.append(collection)

    def to_librarian_json(self):
        if self.original_collections == []:
            return {}
        else:
            return {
                get_relative_path(self.location):
                    [coll.label for coll in self.original_collections]
                    }


class Collection(object):
    def __init__(self, uuid, label, is_new=False):
        self.uuid = uuid
        self.label = label
        self.original_ebooks = []
        self.ebooks = []
        self.is_new = is_new

    def sort_ebooks(self):
        self.ebooks.sort(key=lambda ebook: ebook.uuid)
        self.original_ebooks.sort(key=lambda ebook: ebook.uuid)

    def add_ebook(self, ebook, original=False):
        if original:
            self.original_ebooks.append(ebook)
        else:
            self.ebooks.append(ebook)

    # Build a legacy hashes list from the cdeType & cdeKey
    # couples of our book list
    def build_legacy_hashes_list(self):
        hashes_list = []
        for e in self.original_ebooks:
            # Guard against NULL cdeKeys, which should never happen for books, but have been seen in the wild w/ manually sideloaded stuff...
            if e.cdekey:
                if e.cdekey.startswith('*'):
                    # No ASIN set, we don't care about the cdeType, use it as-is
                    hashes_list.append(e.cdekey)
                else:
                    # Proper or fake ASIN set, build the hash
                    hashes_list.append('#{}^{}'.format(e.cdekey, e.cdetype))
            else:
                log(LIBRARIAN_SYNC, "legacy hash building",
                    "Book %s has no cdeKey?! Skipping it."
                    "(sideloaded book?)" % e.location,
                    "W", display=False)
        return hashes_list

    def to_calibre_plugin_json(self):
        if self.original_ebooks == []:
            return {}
        else:
            return {
                "%s@%s" % (self.label, locale.getdefaultlocale()[0]):
                    {
                        "items": self.build_legacy_hashes_list(),
                        "lastAccess": int(time.time())
                    }
                }


# it would be very, very unlucky to have a collision
# between collection uuid & label...
def find_collection(collections, collection_uuid_or_label):
    for (i, collection) in enumerate(collections):
        if collection.uuid == collection_uuid_or_label or\
           collection.label == collection_uuid_or_label:
            return i
    return -1


# same for uuid & location. Note that we add matching an uuid to a cdeKey in
# order to handle the legacy json db schema.
def find_ebook(ebooks, ebook_identifier, regexp=False):
    if regexp:
        pattern = re.compile(ebook_identifier.split("re:")[1], re.UNICODE)
    hits = []
    for (i, ebook) in enumerate(ebooks):
        if not regexp and (ebook.uuid == ebook_identifier or
                           ebook.location == ebook_identifier or
                           ebook.cdekey == ebook_identifier):
            hits.append(i)

        if regexp and (pattern.search(ebook.uuid) or
                       pattern.search(ebook.location) or
                       pattern.search(str(ebook.cdekey))):
            hits.append(i)
    return hits
