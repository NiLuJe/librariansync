#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

from __future__ import absolute_import

import json
import os
import uuid
import sys
import codecs
import re
import time
import traceback
import argparse
import sqlite3
from collections import defaultdict

from cc_update import CCUpdate
from kindle_contents import Ebook, Collection
from kindle_contents import find_collection, find_ebook, list_folder_contents
from kindle_logging import log, LIBRARIAN_SYNC

# -------- Config
KINDLE_DB_PATH = u"/var/local/cc.db"
TAGS = u"../collections.json"
CALIBRE_PLUGIN_FILE = u"/mnt/us/system/collections.json"
EXPORT = u"../exported_collections.json"
KINDLE_EBOOKS_ROOT = u"/mnt/us/documents/"

SELECT_COLLECTION_ENTRIES = u'select p_uuid, p_titles_0_nominal '\
                            u'from Entries where p_type = "Collection"'
SELECT_EBOOK_ENTRIES = u'select p_uuid, p_location, p_cdeKey, p_cdeType '\
                       u'from Entries where p_type = "Entry:Item"'
SELECT_EXISTING_COLLECTIONS = u'select i_collection_uuid, i_member_uuid '\
                              u'from Collections'


# -------- Existing Kindle database entries
def parse_entries(cursor, ignore_empty_collections=False):
    db_ebooks = []
    db_collections = []

    cursor.execute(SELECT_COLLECTION_ENTRIES)
    for (c_uuid, label) in cursor.fetchall():
        db_collections.append(Collection(c_uuid, label))

    cursor.execute(SELECT_EBOOK_ENTRIES)
    for (e_uuid, location, cdekey, cdetype) in cursor.fetchall():
        # only consider user ebooks
        if location is not None and KINDLE_EBOOKS_ROOT in location:
            db_ebooks.append(Ebook(e_uuid, location, cdekey, cdetype))

    cursor.execute(SELECT_EXISTING_COLLECTIONS)
    for (collection_uuid, ebook_uuid) in cursor.fetchall():
        collection_idx = find_collection(db_collections, collection_uuid)
        ebook_idx_list = find_ebook(db_ebooks, ebook_uuid)
        if collection_idx != -1 and ebook_idx_list != []:
            for ebook_idx in ebook_idx_list:
                db_collections[collection_idx].add_ebook(db_ebooks[ebook_idx],
                                                        True)
                db_ebooks[ebook_idx].add_collection(
                    db_collections[collection_idx], True)
        else:
            log(LIBRARIAN_SYNC, u"parse_entries",
                u"Skipping collection {} (collection_idx: {}, ebook_uuid: {})"
                .format(collection_uuid, collection_idx, ebook_uuid),
                u"W", display=False)

    # remove empty collections:
    if ignore_empty_collections:
        db_collections = [c for c in db_collections
                          if len(c.original_ebooks) != 0]

    return db_ebooks, db_collections


# -------- JSON collections
def parse_config(config_file):
    return json.load(open(config_file, 'r'), 'utf8')


def parse_calibre_plugin_config(config_file):
    calibre_plugin_config = json.load(open(config_file, 'r'), 'utf8')
    # handle the locale properly (RegEx borrowed from the KCP)
    coll_name_pattern = re.compile(r'^(.*)@[^@]+$')
    # collection_label: [ebook_uuid, ...]
    collection_members_uuid = defaultdict(list)
    for collection in calibre_plugin_config.keys():
        collection_members_uuid[
            coll_name_pattern.sub(r'\1', collection)
            ].extend(calibre_plugin_config[collection]["items"])
    return collection_members_uuid


def update_lists_from_librarian_json(db_ebooks, db_collections,
                                     collection_contents):

    for (ebook_location,
         ebook_collection_labels_list) in collection_contents.items():
        # find ebook by location
        if ebook_location.startswith("re:"):
            ebook_idx_list = find_ebook(db_ebooks, ebook_location, regexp=True)
        else:
            ebook_idx_list = find_ebook(db_ebooks, os.path.join(
                KINDLE_EBOOKS_ROOT, ebook_location))
        if ebook_idx_list == []:
            log(LIBRARIAN_SYNC, u"update librarian",
                u"Invalid location: %s" % ebook_location.encode("utf8"),
                u"W", display=False)
            continue  # invalid
        for collection_label in ebook_collection_labels_list:
            # find collection by label
            collection_idx = find_collection(db_collections, collection_label)
            if collection_idx == -1:
                # creating new collection object
                db_collections.append(Collection(uuid.uuid4(),
                                                 collection_label,
                                                 is_new=True))
                collection_idx = len(db_collections)-1
            for ebook_idx in ebook_idx_list:
                # udpate ebook
                db_ebooks[ebook_idx].add_collection(
                    db_collections[collection_idx])
                # update collection
                db_collections[collection_idx].add_ebook(db_ebooks[ebook_idx])

    # remove empty collections:
    db_collections = [c for c in db_collections if len(c.ebooks) != 0]

    return db_ebooks, db_collections


# Return a cdeKey, cdeType couple from a legacy json hash
def parse_legacy_hash(legacy_hash):
    if legacy_hash.startswith('#'):
        cdekey, cdetype = legacy_hash[1:].split('^')
    else:
        cdekey = legacy_hash
        # Legacy md5 hash of the full path, there's no cdeType, assume EBOK.
        cdetype = u'EBOK'
    return cdekey, cdetype


def update_lists_from_calibre_plugin_json(db_ebooks, db_collections,
                                          collection_contents):

    for (collection_label, ebook_hashes_list) in collection_contents.items():
        # find collection by label
        collection_idx = find_collection(db_collections, collection_label)
        if collection_idx == -1:
            # creating new collection object
            db_collections.append(Collection(uuid.uuid4(), collection_label,
                                             is_new=True))
            collection_idx = len(db_collections)-1

        for ebook_hash in ebook_hashes_list:
            cdekey, cdetype = parse_legacy_hash(ebook_hash)
            # NOTE: We don't actually use the cdeType. We shouldn't need to,
            # unless we run into the extremely unlikely case of two items with
            # the same cdeKey, but different cdeTypes
            # find ebook by cdeKey
            ebook_idx_list = find_ebook(db_ebooks, cdekey)
            if ebook_idx_list == []:
                log(LIBRARIAN_SYNC, u"update calibre",
                    u"Couldn't match a db uuid to cdeKey %s"
                    u"(book not on device?)" % cdekey,
                    u"W", display=False)
                continue  # invalid
            for ebook_idx in ebook_idx_list:
                # update ebook
                db_ebooks[ebook_idx].add_collection(
                    db_collections[collection_idx])
                # update collection
                db_collections[collection_idx].add_ebook(db_ebooks[ebook_idx])

    # remove empty collections:
    db_collections = [c for c in db_collections if len(c.ebooks) != 0]

    return db_ebooks, db_collections


# -------- Main
def update_cc_db(c, complete_rebuild=True, source="folders"):
    # build dictionaries of ebooks/collections with their uuids
    db_ebooks, db_collections = parse_entries(c,
                                              ignore_empty_collections=False)

    # object that will handle all db updates
    cc = CCUpdate()

    if complete_rebuild:
        # clear all current collections
        for (i, eb) in enumerate(db_ebooks):
            db_ebooks[i].original_collections = []
        for (i, eb) in enumerate(db_collections):
            db_collections[i].original_ebooks = []
        for collection in db_collections:
            cc.delete_collection(collection.uuid)
        db_collections = []

    if source == "calibre_plugin":
        collections_contents = parse_calibre_plugin_config(CALIBRE_PLUGIN_FILE)
        db_ebooks, db_collections = update_lists_from_calibre_plugin_json(
            db_ebooks, db_collections, collections_contents)
    else:
        if source == "folders":
            # parse folder structure
            collections_contents = list_folder_contents()
        else:
            # parse tags json
            collections_contents = parse_config(TAGS)
        db_ebooks, db_collections = update_lists_from_librarian_json(
            db_ebooks, db_collections, collections_contents)

    # updating collections, creating them if necessary
    for collection in db_collections:
        if collection.is_new:
            # create new collections in db
            cc.insert_new_collection_entry(collection.uuid, collection.label)
        # update all 'Collections' entries with new members
        collection.sort_ebooks()
        if collection.ebooks != collection.original_ebooks:
            cc.update_collections_entry(collection.uuid,
                                        [e.uuid for e in collection.ebooks])

    # if firmware requires updating ebook entries
    if cc.is_cc_aware:
        # update all Item:Ebook entries with the number of collections
        # it belongs to.
        for ebook in db_ebooks:
            if len(ebook.collections) != len(ebook.original_collections):
                cc.update_ebook_entry(ebook.uuid, len(ebook.collections))

    # send all the commands to update the database
    cc.execute()


def export_existing_collections(c):
    db_ebooks, db_collections = parse_entries(c, ignore_empty_collections=True)

    export = {}
    for ebook in db_ebooks:
        export.update(ebook.to_librarian_json())

    with codecs.open(EXPORT, "w", "utf8") as export_json:
        export_json.write(json.dumps(export, sort_keys=True, indent=2,
                                     separators=(',', ': '),
                                     ensure_ascii=False))

    export = {}
    for collection in db_collections:
        export.update(collection.to_calibre_plugin_json())

    with codecs.open(CALIBRE_PLUGIN_FILE, "w", "utf8") as export_json:
        export_json.write(json.dumps(export, sort_keys=True, indent=2,
                                     separators=(',', ': '),
                                     ensure_ascii=False))


def delete_all_collections(c):
    # build dictionaries of ebooks/collections with their uuids
    db_ebooks, db_collections = parse_entries(c,
                                              ignore_empty_collections=False)

    # object that will handle all db updates
    cc = CCUpdate()
    for collection in db_collections:
        cc.delete_collection(collection.uuid)
    cc.execute()

# -------------------------------------------------------
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Librarian Sync. Build Kindle'
                                     'collections, fast and without style.')

    parser.add_argument('-x', '--export',    dest='export',
                        action='store_true', default=False,
                        help='export collections.')
    parser.add_argument('-d', '--delete',    dest='delete',
                        action='store_true', default=False,
                        help='delete collections.')
    parser.add_argument('-f', '--folders',   dest='folders',
                        action='store_true', default=False,
                        help='rebuild from folder structure.')
    parser.add_argument('-u', '--update',    dest='update',
                        action='store_true', default=False,
                        help='update collections from librarian.')
    parser.add_argument('-r', '--rebuild',   dest='rebuild',
                        action='store_true', default=False,
                        help='rebuild collections from librarian.')
    parser.add_argument('--update-calibre',  dest='update_calibre',
                        action='store_true', default=False,
                        help='update collections from calibre kindle plugin.')
    parser.add_argument('--rebuild-calibre', dest='rebuild_calibre',
                        action='store_true', default=False,
                        help='rebuild collections from calibre kindle plugin.')

    args = parser.parse_args()

    start = time.time()
    log(LIBRARIAN_SYNC, u"main", u"Starting...")
    try:
        with sqlite3.connect(KINDLE_DB_PATH) as cc_db:
            c = cc_db.cursor()
            if args.rebuild:
                log(LIBRARIAN_SYNC, u"rebuild",
                    u"Rebuilding collections (librarian)...")
                update_cc_db(c, complete_rebuild=True,
                             source="librarian")
            elif args.update:
                log(LIBRARIAN_SYNC, u"update",
                    u"Updating collections (librarian)...")
                update_cc_db(c, complete_rebuild=False,
                             source="librarian")
            elif args.folders:
                log(LIBRARIAN_SYNC, u"rebuild_from_folders",
                    u"Rebuilding collections (folders)...")
                update_cc_db(c, complete_rebuild=True,
                             source="folders")
            elif args.rebuild_calibre:
                log(LIBRARIAN_SYNC, u"rebuild_from_calibre_plugin_json",
                    u"Rebuilding collections (Calibre)...")
                update_cc_db(c, complete_rebuild=True,
                             source="calibre_plugin")
            elif args.update_calibre:
                log(LIBRARIAN_SYNC, u"update_from_calibre_plugin_json",
                    u"Updating collections (Calibre)...")
                update_cc_db(c, complete_rebuild=False,
                             source="calibre_plugin")
            elif args.export:
                log(LIBRARIAN_SYNC, u"export", u"Exporting collections...")
                export_existing_collections(c)
            elif args.delete:
                log(LIBRARIAN_SYNC, u"delete", u"Deleting all collections...")
                delete_all_collections(c)
    except:
        log(LIBRARIAN_SYNC, u"main", u"Something went very wrong.", u"E")
        traceback.print_exc()
    else:
        log(LIBRARIAN_SYNC, u"main", u"Done in %.02fs." % (time.time()-start))
        # Take care of buffered IO & KUAL's IO redirection...
        sys.stdout.flush()
        sys.stderr.flush()
