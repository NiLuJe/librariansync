from __future__ import absolute_import

import sys
import syslog
import six
# Requires a Python snapshot circa 0.15.N-r15585
from _fbink import ffi, lib as fbink

# ------- Logging & user feedback (from the K5 Fonts Hack)

LIBRARIAN_SYNC = "LibrarianSync"

# Setup FBInk to our liking...
FBINK_CFG = ffi.new("FBInkConfig *")
FBINK_CFG.is_quiet = True
FBINK_CFG.is_rpadded = True
FBINK_CFG.row = -6

# And initialize it
fbink.fbink_init(fbink.FBFD_AUTO, FBINK_CFG)


# Pilfered from KindleUnpack, with minor tweaks ;).
# force string to be utf-8 encoded whether unicode or bytestring
def utf8_str(p, enc=sys.getfilesystemencoding()):
    if isinstance(p, six.text_type):
        return p.encode('utf-8')
    if enc != 'utf-8':
        return p.decode(enc).encode('utf-8', 'replace')
    return p


def log(program, function, msg, level="I", display=True):
    global LAST_SHOWN
    # open syslog
    syslog.openlog("system: %s %s:%s:" % (level, program, function))
    # set priority
    priority = syslog.LOG_INFO
    if level == "E":
        priority = syslog.LOG_ERR
    elif level == "W":
        priority = syslog.LOG_WARNING
    priority |= syslog.LOG_LOCAL4
    # write to syslog
    syslog.syslog(priority, msg)
    #
    # NOTE: showlog / showlog -f to check the logs
    #

    if display:
        program_display = " %s: " % program
        displayed = " "
        # If loglevel is anything else than I, add it to our tag
        if level != "I":
            displayed += "[%s] " % level
        displayed += utf8_str(msg)
        # print using FBInk (via cFFI)
        fbink.fbink_print(fbink.FBFD_AUTO, "%s\n%s" % (program_display, displayed), FBINK_CFG)
