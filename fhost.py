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
from flask_migrate import Migrate
from jinja2.exceptions import *
from jinja2 import ChoiceLoader, FileSystemLoader
from hashlib import sha256
from magic import Magic
from mimetypes import guess_extension
import sys
import requests
from short_url import UrlEncoder
from validators import url as url_valid
from pathlib import Path

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

if not app.config["TESTING"]:
    app.config.from_pyfile("config.py")
    app.jinja_loader = ChoiceLoader([
        FileSystemLoader(str(Path(app.instance_path) / "templates")),
        app.jinja_loader
    ])

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

db = SQLAlchemy(app)
migrate = Migrate(app, db)

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

    def get(url):
        u = URL.query.filter_by(url=url).first()

        if not u:
            u = URL(url)
            db.session.add(u)
            db.session.commit()

        return u

class File(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    sha256 = db.Column(db.String, unique = True)
    ext = db.Column(db.UnicodeText)
    mime = db.Column(db.UnicodeText)
    addr = db.Column(db.UnicodeText)
    removed = db.Column(db.Boolean, default=False)
    nsfw_score = db.Column(db.Float)

    def __init__(self, sha256, ext, mime, addr):
        self.sha256 = sha256
        self.ext = ext
        self.mime = mime
        self.addr = addr

    def getname(self):
        return u"{0}{1}".format(su.enbase(self.id, 1), self.ext)

    def geturl(self):
        n = self.getname()

        if self.nsfw_score and self.nsfw_score > app.config["NSFW_THRESHOLD"]:
            return url_for("get", path=n, _external=True, _anchor="nsfw") + "\n"
        else:
            return url_for("get", path=n, _external=True) + "\n"

    def store(file_, addr):
        data = file_.stream.read()
        digest = sha256(data).hexdigest()

        def get_mime():
            guess = mimedetect.from_buffer(data)
            app.logger.debug(f"MIME - specified: '{file_.content_type}' - detected: '{guess}'")

            if not file_.content_type or not "/" in file_.content_type or file_.content_type == "application/octet-stream":
                mime = guess
            else:
                mime = file_.content_type

            if mime in app.config["FHOST_MIME_BLACKLIST"] or guess in app.config["FHOST_MIME_BLACKLIST"]:
                abort(415)

            if mime.startswith("text/") and not "charset" in mime:
                mime += "; charset=utf-8"

            return mime

        def get_ext(mime):
            ext = "".join(Path(file_.filename).suffixes[-2:])
            gmime = mime[:mime.find(";")]
            guess = guess_extension(gmime)

            app.logger.debug(f"extension - specified: '{ext}' - detected: '{guess}'")

            if not ext:
                if gmime in app.config["FHOST_EXT_OVERRIDE"]:
                    ext = app.config["FHOST_EXT_OVERRIDE"][gmime]
                else:
                    ext = guess_extension(gmime)

            return ext[:app.config["FHOST_MAX_EXT_LENGTH"]] or ".bin"

        f = File.query.filter_by(sha256=digest).first()

        if f:
            if f.removed:
                abort(451)
        else:
            mime = get_mime()
            ext = get_ext(mime)
            f = File(digest, ext, mime, addr)

        f.addr = addr

        storage = Path(app.config["FHOST_STORAGE_PATH"])
        storage.mkdir(parents=True, exist_ok=True)
        p = storage / digest

        if not p.is_file():
            file_.stream.seek(0)
            file_.save(p)
        else:
            p.touch()

        if not f.nsfw_score and app.config["NSFW_DETECT"]:
            f.nsfw_score = nsfw.detect(p)

        db.session.add(f)
        db.session.commit()
        return f

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

    u = URL.get(url)

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

    sf = File.store(f, addr)

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
    path = Path(path.split("/", 1)[0])
    sufs = "".join(path.suffixes[-2:])
    name = path.name[:-len(sufs) or None]
    id = su.debase(name)

    if sufs:
        f = File.query.get(id)

        if f and f.ext == sufs:
            if f.removed:
                abort(451)

            fpath = Path(app.config["FHOST_STORAGE_PATH"]) / f.sha256

            if not fpath.is_file():
                abort(404)

            if app.config["FHOST_USE_X_ACCEL_REDIRECT"]:
                response = make_response()
                response.headers["Content-Type"] = f.mime
                response.headers["Content-Length"] = fpath.stat().st_size
                response.headers["X-Accel-Redirect"] = "/" + str(fpath)
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
