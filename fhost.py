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
from sqlalchemy import and_
from jinja2.exceptions import *
from jinja2 import ChoiceLoader, FileSystemLoader
from hashlib import sha256
from magic import Magic
from mimetypes import guess_extension
import click
import os
import sys
import time
import typing
import requests
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

class URL(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    url = db.Column(db.UnicodeText, unique = True)

    def __init__(self, url):
        self.url = url

    def getname(self):
        return su.enbase(self.id)

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
    expiration = db.Column(db.BigInteger)

    def __init__(self, sha256, ext, mime, addr, expiration):
        self.sha256 = sha256
        self.ext = ext
        self.mime = mime
        self.addr = addr
        self.expiration = expiration

    def getname(self):
        return u"{0}{1}".format(su.enbase(self.id), self.ext)

    def geturl(self):
        n = self.getname()

        if self.nsfw_score and self.nsfw_score > app.config["NSFW_THRESHOLD"]:
            return url_for("get", path=n, _external=True, _anchor="nsfw") + "\n"
        else:
            return url_for("get", path=n, _external=True) + "\n"

    """
    requested_expiration can be:
        - None, to use the longest allowed file lifespan
        - a duration (in hours) that the file should live for
        - a timestamp in epoch millis that the file should expire at

    Any value greater that the longest allowed file lifespan will be rounded down to that
    value.
    """
    def store(file_, requested_expiration: typing.Optional[int], addr):
        data = file_.read()
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
            gmime = mime.split(";")[0]
            guess = guess_extension(gmime)

            app.logger.debug(f"extension - specified: '{ext}' - detected: '{guess}'")

            if not ext:
                if gmime in app.config["FHOST_EXT_OVERRIDE"]:
                    ext = app.config["FHOST_EXT_OVERRIDE"][gmime]
                else:
                    ext = guess_extension(gmime)

            return ext[:app.config["FHOST_MAX_EXT_LENGTH"]] or ".bin"

        # Returns the epoch millisecond that this file should expire
        #
        # Uses the expiration time provided by the user (requested_expiration)
        # upper-bounded by an algorithm that computes the size based on the size of the
        # file.
        #
        # That is, all files are assigned a computed expiration, which can voluntarily
        # shortened by the user either by providing a timestamp in epoch millis or a
        # duration in hours.
        def get_expiration() -> int:
            current_epoch_millis = time.time() * 1000;

            # Maximum lifetime of the file in milliseconds
            this_files_max_lifespan = get_max_lifespan(len(data));

            # The latest allowed expiration date for this file, in epoch millis
            this_files_max_expiration = this_files_max_lifespan + 1000 * time.time();

            if requested_expiration is None:
                return this_files_max_expiration
            elif requested_expiration < 1650460320000:
                # Treat the requested expiration time as a duration in hours
                requested_expiration_ms = requested_expiration * 60 * 60 * 1000
                return min(this_files_max_expiration, current_epoch_millis + requested_expiration_ms)
            else:
                # Treat the requested expiration time as a timestamp in epoch millis
                return min(this_files_max_expiration, requested_expiration);

        f = File.query.filter_by(sha256=digest).first()
        if f:
            # If the file already exists
            if f.removed:
                # The file was removed by moderation, so don't accept it back
                abort(451)
            if f.expiration is None:
                # The file has expired, so give it a new expiration date
                f.expiration = get_expiration()
            else:
                # The file already exists, update the expiration if needed
                f.expiration = max(f.expiration, get_expiration())
        else:
            mime = get_mime()
            ext = get_ext(mime)
            expiration = get_expiration()
            f = File(digest, ext, mime, addr, expiration)

        f.addr = addr

        storage = Path(app.config["FHOST_STORAGE_PATH"])
        storage.mkdir(parents=True, exist_ok=True)
        p = storage / digest

        if not p.is_file():
            with open(p, "wb") as of:
                of.write(data)

        if not f.nsfw_score and app.config["NSFW_DETECT"]:
            f.nsfw_score = nsfw.detect(p)

        db.session.add(f)
        db.session.commit()
        return f



class UrlEncoder(object):
    def __init__(self,alphabet, min_length):
        self.alphabet = alphabet
        self.min_length = min_length

    def enbase(self, x):
        n = len(self.alphabet)
        str = ""
        while x > 0:
            str = (self.alphabet[int(x % n)]) + str
            x = int(x // n)
        padding = self.alphabet[0] * (self.min_length - len(str))
        return '%s%s' % (padding, str)

    def debase(self, x):
        n = len(self.alphabet)
        result = 0
        for i, c in enumerate(reversed(x)):
            result += self.alphabet.index(c) * (n ** i)
        return result

su = UrlEncoder(alphabet=app.config["URL_ALPHABET"], min_length=1)

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
        with app.open_instance_resource(app.config["FHOST_UPLOAD_BLACKLIST"], "r") as bl:
            check = addr.lstrip("::ffff:")
            for l in bl.readlines():
                if not l.startswith("#"):
                    if check == l.rstrip():
                        return True

    return False

"""
requested_expiration can be:
    - None, to use the longest allowed file lifespan
    - a duration (in hours) that the file should live for
    - a timestamp in epoch millis that the file should expire at

Any value greater that the longest allowed file lifespan will be rounded down to that
value.
"""
def store_file(f, requested_expiration:  typing.Optional[int], addr):
    if in_upload_bl(addr):
        return "Your host is blocked from uploading files.\n", 451

    sf = File.store(f, requested_expiration, addr)

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

            f = urlfile(read=r.raw.read, content_type=r.headers["content-type"], filename="")

            return store_file(f, None, addr)
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
            try:
                # Store the file with the requested expiration date
                return store_file(
                    request.files["file"],
                    int(request.form["expires"]),
                    request.remote_addr
                )
            except ValueError:
                # The requested expiration date wasn't properly formed
                abort(400)
            except KeyError:
                # No expiration date was requested, store with the max lifespan
                return store_file(
                    request.files["file"],
                    None,
                    request.remote_addr
                )
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

@app.cli.command("prune")
def prune():
    """
    Clean up expired files

    Deletes any files from the filesystem which have hit their expiration time.  This
    doesn't remove them from the database, only from the filesystem.  It's recommended
    that server owners run this command regularly, or set it up on a timer.
    """
    current_time = time.time() * 1000;

    # The path to where uploaded files are stored
    storage = Path(app.config["FHOST_STORAGE_PATH"])

    # A list of all files who've passed their expiration times
    expired_files = File.query\
        .where(
            and_(
                File.expiration.is_not(None),
                File.expiration < current_time
            )
        )

    files_removed = 0;

    # For every expired file...
    for file in expired_files:
        # Log the file we're about to remove
        file_name = file.getname()
        file_hash = file.sha256
        file_path = storage / file_hash
        print(f"Removing expired file {file_name} [{file_hash}]")

        # Remove it from the file system
        try:
            os.remove(file_path)
            files_removed += 1;
        except FileNotFoundError:
            pass # If the file was already gone, we're good
        except OSError as e:
            print(e)
            print(
                "\n------------------------------------"
                "Encountered an error while trying to remove file {file_path}.  Double"
                "check to make sure the server is configured correctly, permissions are"
                "okay, and everything is ship shape, then try again.")
            return;

        # Finally, mark that the file was removed
        file.expiration = None;
    db.session.commit()

    print(f"\nDone!  {files_removed} file(s) removed")

""" For a file of a given size, determine the largest allowed lifespan of that file

Based on the current app's configuration:  Specifically, the MAX_CONTENT_LENGTH, as well
as FHOST_{MIN,MAX}_EXPIRATION.

This lifespan may be shortened by a user's request, but no files should be allowed to
expire at a point after this number.

Value returned is a duration in milliseconds.
"""
def get_max_lifespan(filesize: int) -> int:
    min_exp = app.config.get("FHOST_MIN_EXPIRATION", 30 * 24 * 60 * 60 * 1000)
    max_exp = app.config.get("FHOST_MAX_EXPIRATION", 365 * 24 * 60 * 60 * 1000)
    max_size = app.config.get("MAX_CONTENT_LENGTH", 256 * 1024 * 1024)
    return min_exp + int((-max_exp + min_exp) * (filesize / max_size - 1) ** 3)
