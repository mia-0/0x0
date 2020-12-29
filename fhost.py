#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    Copyright © 2020 Mia Herkt
    Licensed under the EUPL, Version 1.2 or - as soon as approved
    by the European Commission - subsequent versions of the EUPL
    (the "License");
    You may not use this work except in compliance with the License.
    You may obtain a copy of the license at:

        https://joinup.ec.europa.eu/software/page/eupl

    Unless required by applicable law or agreed to in writing,
    software distributed under the License is distributed on an
    "AS IS" basis, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
    either express or implied.
    See the License for the specific language governing permissions
    and limitations under the License.
"""

from flask import Flask, abort, make_response, redirect, request, send_from_directory, url_for, Response, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_script import Manager
from flask_migrate import Migrate, MigrateCommand
from jinja2.exceptions import *
from hashlib import sha256
from magic import Magic
from mimetypes import guess_extension
import os, sys
import requests
from short_url import UrlEncoder
from validators import url as url_valid

app = Flask(__name__, instance_relative_config=True)
app.config.update(
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    PREFERRED_URL_SCHEME = "https", # nginx users: make sure to have 'uwsgi_param UWSGI_SCHEME $scheme;' in your config
    MAX_CONTENT_LENGTH = 256 * 1024 * 1024,
    MAX_URL_LENGTH = 4096,
    USE_X_SENDFILE = False,
    FHOST_USE_X_ACCEL_REDIRECT = True, # expect nginx by default
    FHOST_STORAGE_PATH = "up",
    FHOST_MAX_EXT_LENGTH = 9,
    FHOST_EXT_OVERRIDE = {
        "audio/flac" : ".flac",
        "image/gif" : ".gif",
        "image/jpeg" : ".jpg",
        "image/png" : ".png",
        "image/svg+xml" : ".svg",
        "video/webm" : ".webm",
        "video/x-matroska" : ".mkv",
        "application/octet-stream" : ".bin",
        "text/plain" : ".log",
        "text/plain" : ".txt",
        "text/x-diff" : ".diff",
    },
    FHOST_MIME_BLACKLIST = [
        "application/x-dosexec",
        "application/java-archive",
        "application/java-vm"
    ],
    FHOST_UPLOAD_BLACKLIST = None,
    NSFW_DETECT = False,
    NSFW_THRESHOLD = 0.608,
    URL_ALPHABET = "DEQhd2uFteibPwq0SWBInTpA_jcZL5GKz3YCR14Ulk87Jors9vNHgfaOmMXy6Vx-",
)

app.config.from_pyfile("config.py")

if app.config["DEBUG"]:
    app.config["FHOST_USE_X_ACCEL_REDIRECT"] = False

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

su = UrlEncoder(alphabet=app.config["URL_ALPHABET"], block_size=16)

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
    if app.config["FHOST_UPLOAD_BLACKLIST"]:
        with app.open_instance_resource(app.config["FHOST_UPLOAD_BLACKLIST"]) as bl:
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
            abort(451)

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
        abort(400)

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
            abort(413)
    else:
        abort(411)

@app.route("/<path:path>")
def get(path):
    p = os.path.splitext(path)
    id = su.debase(p[0])

    if p[1]:
        f = File.query.get(id)

        if f and f.ext == p[1]:
            if f.removed:
                abort(451)

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
        return render_template("index.html")

@app.route("/robots.txt")
def robots():
    return """User-agent: *
Disallow: /
"""

@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(411)
@app.errorhandler(413)
@app.errorhandler(414)
@app.errorhandler(415)
@app.errorhandler(451)
def ehandler(e):
    try:
        return render_template(f"{e.code}.html", id=id), e.code
    except TemplateNotFound:
        return "Segmentation fault\n", e.code
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
