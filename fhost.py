#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, abort, escape, make_response, redirect, request, send_from_directory, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from flask_script import Manager
from flask_migrate import Migrate, MigrateCommand
from hashlib import sha256
from humanize import naturalsize
from magic import Magic
from mimetypes import guess_extension
import os, sys
import requests
from short_url import UrlEncoder
from validators import url as url_valid

app = Flask(__name__)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///db.sqlite" # "postgresql://0x0@/0x0"
app.config["PREFERRED_URL_SCHEME"] = "https" # nginx users: make sure to have 'uwsgi_param UWSGI_SCHEME $scheme;' in your config
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024
app.config["MAX_URL_LENGTH"] = 4096
app.config["FHOST_STORAGE_PATH"] = "up"
app.config["FHOST_USE_X_ACCEL_REDIRECT"] = True # expect nginx by default
app.config["USE_X_SENDFILE"] = False
app.config["FHOST_EXT_OVERRIDE"] = {
    "audio/flac" : ".flac",
    "image/gif" : ".gif",
    "image/jpeg" : ".jpg",
    "image/png" : ".png",
    "image/svg+xml" : ".svg",
    "video/webm" : ".webm",
    "video/x-matroska" : ".mkv",
    "application/octet-stream" : ".bin",
    "text/plain" : ".txt",
    "text/x-diff" : ".diff",
}

# default blacklist to avoid AV mafia extortion
app.config["FHOST_MIME_BLACKLIST"] = [
    "application/x-dosexec",
    "application/java-archive",
    "application/java-vm"
]

app.config["FHOST_UPLOAD_BLACKLIST"] = "tornodes.txt"

app.config["NSFW_DETECT"] = False
app.config["NSFW_THRESHOLD"] = 0.608

if app.config["NSFW_DETECT"]:
    from nsfw_detect import NSFWDetector
    nsfw = NSFWDetector()

try:
    mimedetect = Magic(mime=True, mime_encoding=False)
except:
    print("""Error: You have installed the wrong version of the 'magic' module.
Please install python-magic.""")
    sys.exit(1)

if not os.path.exists(app.config["FHOST_STORAGE_PATH"]):
    os.mkdir(app.config["FHOST_STORAGE_PATH"])

db = SQLAlchemy(app)
migrate = Migrate(app, db)

manager = Manager(app)
manager.add_command("db", MigrateCommand)

su = UrlEncoder(alphabet='DEQhd2uFteibPwq0SWBInTpA_jcZL5GKz3YCR14Ulk87Jors9vNHgfaOmMXy6Vx-', block_size=16)

class URL(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    url = db.Column(db.UnicodeText, unique = True)

    def __init__(self, url):
        self.url = url

    def getname(self):
        return su.enbase(self.id, 1)

    def geturl(self):
        return url_for("get", path=self.getname(), _external=True) + "\n"

class File(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    sha256 = db.Column(db.String, unique = True)
    ext = db.Column(db.UnicodeText)
    mime = db.Column(db.UnicodeText)
    addr = db.Column(db.UnicodeText)
    removed = db.Column(db.Boolean, default=False)
    nsfw_score = db.Column(db.Float)

    def __init__(self, sha256, ext, mime, addr, nsfw_score):
        self.sha256 = sha256
        self.ext = ext
        self.mime = mime
        self.addr = addr
        self.nsfw_score = nsfw_score

    def getname(self):
        return u"{0}{1}".format(su.enbase(self.id, 1), self.ext)

    def geturl(self):
        n = self.getname()

        if self.nsfw_score and self.nsfw_score > app.config["NSFW_THRESHOLD"]:
            return url_for("get", path=n, _external=True, _anchor="nsfw") + "\n"
        else:
            return url_for("get", path=n, _external=True) + "\n"

    def pprint(self):
        print("url: {}".format(self.getname()))
        vals = vars(self)

        for v in vals:
            if not v.startswith("_sa"):
                print("{}: {}".format(v, vals[v]))

def getpath(fn):
    return os.path.join(app.config["FHOST_STORAGE_PATH"], fn)

def fhost_url(scheme=None):
    if not scheme:
        return url_for(".fhost", _external=True).rstrip("/")
    else:
        return url_for(".fhost", _external=True, _scheme=scheme).rstrip("/")

def is_fhost_url(url):
    return url.startswith(fhost_url()) or url.startswith(fhost_url("https"))

def shorten(url):
    if len(url) > app.config["MAX_URL_LENGTH"]:
        abort(414)

    if not url_valid(url) or is_fhost_url(url) or "\n" in url:
        abort(400)

    existing = URL.query.filter_by(url=url).first()

    if existing:
        return existing.geturl()
    else:
        u = URL(url)
        db.session.add(u)
        db.session.commit()

        return u.geturl()

def in_upload_bl(addr):
    if os.path.isfile(app.config["FHOST_UPLOAD_BLACKLIST"]):
        with open(app.config["FHOST_UPLOAD_BLACKLIST"], "r") as bl:
            check = addr.lstrip("::ffff:")
            for l in bl.readlines():
                if not l.startswith("#"):
                    if check == l.rstrip():
                        return True

    return False

def store_file(f, addr):
    if in_upload_bl(addr):
        return "Your host is blocked from uploading files.\n", 451

    data = f.stream.read()
    digest = sha256(data).hexdigest()
    existing = File.query.filter_by(sha256=digest).first()

    if existing:
        if existing.removed:
            return legal()

        epath = getpath(existing.sha256)

        if not os.path.exists(epath):
            with open(epath, "wb") as of:
                of.write(data)

        if existing.nsfw_score == None:
            if app.config["NSFW_DETECT"]:
                existing.nsfw_score = nsfw.detect(epath)

        os.utime(epath, None)
        existing.addr = addr
        db.session.commit()

        return existing.geturl()
    else:
        guessmime = mimedetect.from_buffer(data)

        if not f.content_type or not "/" in f.content_type or f.content_type == "application/octet-stream":
            mime = guessmime
        else:
            mime = f.content_type

        if mime in app.config["FHOST_MIME_BLACKLIST"] or guessmime in app.config["FHOST_MIME_BLACKLIST"]:
            abort(415)

        if mime.startswith("text/") and not "charset" in mime:
            mime += "; charset=utf-8"

        ext = os.path.splitext(f.filename)[1]

        if not ext:
            gmime = mime.split(";")[0]

            if not gmime in app.config["FHOST_EXT_OVERRIDE"]:
                ext = guess_extension(gmime)
            else:
                ext = app.config["FHOST_EXT_OVERRIDE"][gmime]
        else:
            ext = ext[:8]

        if not ext:
            ext = ".bin"

        spath = getpath(digest)

        with open(spath, "wb") as of:
            of.write(data)

        if app.config["NSFW_DETECT"]:
            nsfw_score = nsfw.detect(spath)
        else:
            nsfw_score = None

        sf = File(digest, ext, mime, addr, nsfw_score)
        db.session.add(sf)
        db.session.commit()

        return sf.geturl()

def store_url(url, addr):
    if is_fhost_url(url):
        return segfault(508)

    h = { "Accept-Encoding" : "identity" }
    r = requests.get(url, stream=True, verify=False, headers=h)

    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        return str(e) + "\n"

    if "content-length" in r.headers:
        l = int(r.headers["content-length"])

        if l < app.config["MAX_CONTENT_LENGTH"]:
            def urlfile(**kwargs):
                return type('',(),kwargs)()

            f = urlfile(stream=r.raw, content_type=r.headers["content-type"], filename="")

            return store_file(f, addr)
        else:
            hl = naturalsize(l, binary = True)
            hml = naturalsize(app.config["MAX_CONTENT_LENGTH"], binary=True)

            return "Remote file too large ({0} > {1}).\n".format(hl, hml), 413
    else:
        return "Could not determine remote file size (no Content-Length in response header; shoot admin).\n", 411

@app.route("/<path:path>")
def get(path):
    p = os.path.splitext(path)
    id = su.debase(p[0])

    if p[1]:
        f = File.query.get(id)

        if f and f.ext == p[1]:
            if f.removed:
                return legal()

            fpath = getpath(f.sha256)

            if not os.path.exists(fpath):
                abort(404)

            fsize = os.path.getsize(fpath)

            if app.config["FHOST_USE_X_ACCEL_REDIRECT"]:
                response = make_response()
                response.headers["Content-Type"] = f.mime
                response.headers["Content-Length"] = fsize
                response.headers["X-Accel-Redirect"] = "/" + fpath
                return response
            else:
                return send_from_directory(app.config["FHOST_STORAGE_PATH"], f.sha256, mimetype = f.mime)
    else:
        u = URL.query.get(id)

        if u:
            return redirect(u.url)

    abort(404)

@app.route("/dump_urls/")
@app.route("/dump_urls/<int:start>")
def dump_urls(start=0):
    meta = "#FORMAT: BEACON\n#PREFIX: {}/\n\n".format(fhost_url("https"))

    def gen():
        yield meta

        for url in URL.query.order_by(URL.id.asc()).offset(start):
            if url.url.startswith("http") or url.url.startswith("https"):
                bar = "|"
            else:
                bar = "||"

            yield url.getname() + bar + url.url + "\n"

    return Response(gen(), mimetype="text/plain")

@app.route("/", methods=["GET", "POST"])
def fhost():
    if request.method == "POST":
        sf = None

        if "file" in request.files:
            return store_file(request.files["file"], request.remote_addr)
        elif "url" in request.form:
            return store_url(request.form["url"], request.remote_addr)
        elif "shorten" in request.form:
            return shorten(request.form["shorten"])

        abort(400)
    else:
        fmts = list(app.config["FHOST_EXT_OVERRIDE"])
        fmts.sort()
        maxsize = naturalsize(app.config["MAX_CONTENT_LENGTH"], binary=True)
        maxsizenum, maxsizeunit = maxsize.split(" ")
        maxsizenum = float(maxsizenum)
        maxsizehalf = maxsizenum / 2

        if maxsizenum.is_integer():
            maxsizenum = int(maxsizenum)
        if maxsizehalf.is_integer():
            maxsizehalf = int(maxsizehalf)

        return """<pre>
THE NULL POINTER
================

HTTP POST files here:
    curl -F'file=@yourfile.png' {0}
You can also POST remote URLs:
    curl -F'url=http://example.com/image.jpg' {0}
Or you can shorten URLs:
    curl -F'shorten=http://example.com/some/long/url' {0}

File URLs are valid for at least 30 days and up to a year (see below).
Shortened URLs do not expire.

Maximum file size: {1}
Not allowed: {5}


FILE RETENTION PERIOD
---------------------

retention = min_age + (-max_age + min_age) * pow((file_size / max_size - 1), 3)

   days
    365 |  \\
        |   \\
        |    \\
        |     \\
        |      \\
        |       \\
        |        ..
        |          \\
  197.5 | ----------..-------------------------------------------
        |             ..
        |               \\
        |                ..
        |                  ...
        |                     ..
        |                       ...
        |                          ....
        |                              ......
     30 |                                    ....................
          0{2}{3}
           {4}


ABUSE
-----

If you would like to request permanent deletion, please contact lachs0r via
IRC on Freenode, or send an email to lachs0r@(this domain).

Please allow up to 24 hours for a response.
</pre>
""".format(fhost_url(),
           maxsize, str(maxsizehalf).rjust(27), str(maxsizenum).rjust(27),
           maxsizeunit.rjust(54),
           ", ".join(app.config["FHOST_MIME_BLACKLIST"]))

@app.route("/robots.txt")
def robots():
    return """User-agent: *
Disallow: /
"""

def legal():
    return "451 Unavailable For Legal Reasons\n", 451

@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(414)
@app.errorhandler(415)
def segfault(e):
    return "Segmentation fault\n", e.code

@app.errorhandler(404)
def notfound(e):
    return u"""<pre>Process {0} stopped
* thread #1: tid = {0}, {1:#018x}, name = '{2}'
    frame #0:
Process {0} stopped
* thread #8: tid = {0}, {3:#018x} fhost`get(path='{4}') + 27 at fhost.c:139, name = 'fhost/responder', stop reason = invalid address (fault address: 0x30)
    frame #0: {3:#018x} fhost`get(path='{4}') + 27 at fhost.c:139
   136   get(SrvContext *ctx, const char *path)
   137   {{
   138       StoredObj *obj = ctx->store->query(shurl_debase(path));
-> 139       switch (obj->type) {{
   140           case ObjTypeFile:
   141               ctx->serve_file_id(obj->id);
   142               break;
(lldb) q</pre>
""".format(os.getpid(), id(app), "fhost", id(get), escape(request.path)), e.code

@manager.command
def debug():
    app.config["FHOST_USE_X_ACCEL_REDIRECT"] = False
    app.run(debug=True, port=4562,host="0.0.0.0")

@manager.command
def permadelete(name):
    id = su.debase(name)
    f = File.query.get(id)

    if f:
        if os.path.exists(getpath(f.sha256)):
            os.remove(getpath(f.sha256))
        f.removed = True
        db.session.commit()

@manager.command
def query(name):
    id = su.debase(name)
    f = File.query.get(id)

    if f:
        f.pprint()

@manager.command
def queryhash(h):
    f = File.query.filter_by(sha256=h).first()

    if f:
        f.pprint()

@manager.command
def queryaddr(a, nsfw=False, removed=False):
    res = File.query.filter_by(addr=a)

    if not removed:
        res = res.filter(File.removed != True)

    if nsfw:
        res = res.filter(File.nsfw_score > app.config["NSFW_THRESHOLD"])

    for f in res:
        f.pprint()

@manager.command
def deladdr(a):
    res = File.query.filter_by(addr=a).filter(File.removed != True)

    for f in res:
        if os.path.exists(getpath(f.sha256)):
            os.remove(getpath(f.sha256))
        f.removed = True

    db.session.commit()

def nsfw_detect(f):
    try:
        open(f["path"], 'r').close()
        f["nsfw_score"] = nsfw.detect(f["path"])
        return f
    except:
        return None

@manager.command
def update_nsfw():
    if not app.config["NSFW_DETECT"]:
        print("NSFW detection is disabled in app config")
        return 1

    from multiprocessing import Pool
    import tqdm

    res = File.query.filter_by(nsfw_score=None, removed=False)

    with Pool() as p:
        results = []
        work = [{ "path" : getpath(f.sha256), "id" : f.id} for f in res]

        for r in tqdm.tqdm(p.imap_unordered(nsfw_detect, work), total=len(work)):
            if r:
                results.append({"id": r["id"], "nsfw_score" : r["nsfw_score"]})

        db.session.bulk_update_mappings(File, results)
        db.session.commit()


@manager.command
def querybl(nsfw=False, removed=False):
    blist = []
    if os.path.isfile(app.config["FHOST_UPLOAD_BLACKLIST"]):
        with open(app.config["FHOST_UPLOAD_BLACKLIST"], "r") as bl:
            for l in bl.readlines():
                if not l.startswith("#"):
                    if not ":" in l:
                        blist.append("::ffff:" + l.rstrip())
                    else:
                        blist.append(l.strip())

    res = File.query.filter(File.addr.in_(blist))

    if not removed:
        res = res.filter(File.removed != True)

    if nsfw:
        res = res.filter(File.nsfw_score > app.config["NSFW_THRESHOLD"])

    for f in res:
        f.pprint()

if __name__ == "__main__":
    manager.run()
