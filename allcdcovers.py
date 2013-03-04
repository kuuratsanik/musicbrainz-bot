#!/usr/bin/env python2
# http://www.allcdcovers.com/show/63158/acid_drinkers_vile_vicious_vision_1994_retail_cd/front

import sys
import os
import re
import pprint
from hashlib import sha1
import mechanize

from editing import MusicBrainzClient
import utils
import config as cfg

ACC_CACHE = 'acc-cache'

utils.monkeypatch_mechanize()

def re_find1(regexp, string):
    m = re.findall(regexp, string)
    if len(m) != 1:
        pat = getattr(regexp, 'pattern', regexp)
        if len(string) > 200:
            filename = '/tmp/debug.html'
            with open(filename, 'wb') as f:
                f.write(string)
            raise AssertionError("Expression %s matched %d times, see %s" % (pat, len(m), filename))
        else:
            raise AssertionError("Expression %s matched %d times: %r" % (pat, len(m), string))
    return m[0]

# Progress file - prevent duplicate uplpoads
DBFILE = os.path.join(ACC_CACHE, 'progress.db')
try:
    statefile = open(DBFILE, 'r+')
    state = set(x.strip() for x in statefile.readlines())
except IOError: # Not found? Try writing
    statefile = open(DBFILE, 'w')
    state = set()

def done(line):
    assert line not in state
    statefile.write("%s\n" % line)
    statefile.flush()
    state.add(line)

acc_url_rec = re.compile('/show/([0-9]+)/[^/-]+/([a-z]+)')
# <div class="thumbnail"><a href="/show/63158/acid_drinkers_vile_vicious_vision_1994_retail_cd/back"><img alt="Back" [...]
#acc_show_re = '"(/show/%s/[^/-]+/(front|back|inside|inlay|cd))"'
acc_show_re = '"(/show/%s/[^/-]+/([a-z]+))"'
# <a href="/download/97e2d4d994aa7ca42da524ca333ff8d9/263803/8c4a7a3a4515ad214846617c90262367/51326581/acid_drinkers_vile_vicious_vision_1997_retail_cd-front">
acc_download_re = '"(/download/[0-9a-f]{32}/%s/[0-9a-f]{32}/[0-9a-f]+/([^/-]+-(front|back|inside|inlay|cd)))"'
# Content-Disposition: inline; filename=allcdcovers.jpg
disposition_re = '(?:; ?|^)filename=((?:[^/]+).jpg)'

ERR_SHA1 = '5dd9c1734067f7a6ee8791961130b52f804211ce'
def download_cover(release_id, typ, resp=None, data=None):
    href, fragment, dtyp = re_find1(acc_download_re % re.escape(release_id), data)

    filename = os.path.join(ACC_CACHE, "[AllCDCovers]_%s.jpg" % fragment)
    referrer = resp.geturl()

    #print dtyp, href
    #print 'Referrer', referrer
    assert typ == dtyp, "%s != %s" % (typ, dtyp)

    cov = {
       'referrer': referrer,
       'type': typ,
       'file': filename,
       'title': br.title(),
    }
    if os.path.exists(filename):
        print "SKIP download, already done: %r" % filename
        cov['cached'] = True
        return cov

    resp = br.open_novisit(href)
    disp = resp.info().getheader('Content-Disposition')
    tmp_name = re_find1(disposition_re, disp)
    if tmp_name == 'allcdcovers.jpg':
        resp.close()
        raise Exception("Got response filename %r, URL is stale? %r" % (tmp_name, href))
    #filename = os.path.join(ACC_CACHE, tmp_name)
    print "Downloading to %r" % (filename)

    data = resp.read()
    resp.close()
    if sha1(data).hexdigest() == ERR_SHA1:
        raise Exception("Got error image back! URL is stale? %r" % href)

    with open(filename, 'wb') as f:
        #print "Saving %s as %r" % (typ, filename)
        f.write(data)

    return cov

def fetch_covers(base_url):
    release_id, typ = re_find1(acc_url_rec, base_url)

    resp = br.open(base_url)
    data = resp.read()

    pages = list(set(re.findall(acc_show_re % re.escape(release_id), data)))
    #pprint.pprint(pages)
    #print 'Pages', pages
    covers = []

    cov = download_cover(release_id, typ, resp, data)
    #pprint.pprint(cov)
    covers.append(cov)

    for href, typ in pages:
        if href in base_url:
            continue

        resp = br.open(href)
        data = resp.read()
        cov = download_cover(release_id, typ, resp, data)
        #pprint.pprint(cov)
        covers.append(cov)

    return covers

ordering = {
    'front': 0,
    'back': 1,
    'inside': 2,
    'inlay': 3,
    'cd': 4,
}
def cov_order(cov):
    return ordering[cov['type']]

COMMENT = "AllCDCovers"
def upload_covers(covers, mbid):
    for cov in sorted(covers, key=cov_order):
        upload_id = "%s %s" % (mbid, cov['referrer'])
        if upload_id in state:
            print "SKIP upload, already done: %r" % cov['file']
            continue

        # type can be: front, back, inside, inlay, cd
        if cov['type'] == 'cd':
            types = ['medium']
        elif cov['type'] == 'inside':
            types = ['booklet']
        elif cov['type'] == 'inlay':
            types = ['tray']
            # AllCDCovers types are sometimes confused. If 'inside' cover exists then 'inlay' refers to Tray, otherwise Booklet
            #if any(c['type'] == 'inside' for c in covers):
            #    types = ['tray']
            #else:
            #    types = ['booklet']
        else:
            types = [cov['type']]

        note = "\"%(title)s\"\nType: %(type)s\n%(referrer)s" % (cov)

        print "Uploading %r from %r" % (types, cov['file'])
        # Doesn't work: position = '0' if cov['type'] == 'front' else
        # ValueError: control 'add-cover-art.position' is readonly
        mb.add_cover_art(mbid, cov['file'], types, None, COMMENT, note, False, False)

        done(upload_id)

def handle_acc_covers(url, mbid):
    mburl = '%s/release/%s/cover-art' % (cfg.MB_SITE, mbid)
    covers = fetch_covers(url)
    print "Uploading to", mburl
    upload_covers(covers, mbid)

    print "Done!", mburl

uuid_rec = re.compile('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
def bot_main():
    init()
    url = sys.argv[1]
    mbid = re_find1(uuid_rec, sys.argv[2])

    handle_acc_covers(url, mbid)

def init():
    global mb, br
    mb = MusicBrainzClient(cfg.MB_USERNAME, cfg.MB_PASSWORD, cfg.MB_SITE)

    br = mechanize.Browser()
    br.set_handle_robots(False) # no robots
    br.set_handle_refresh(False) # can sometimes hang without this
    br.addheaders = [('User-agent', 'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.1) Gecko/2008071615 Fedora/3.0.1-1.fc9 Firefox/3.0.1')]

if __name__ == '__main__':
    bot_main()
