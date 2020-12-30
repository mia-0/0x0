import pytest
import tempfile
import os
from flask_migrate import upgrade as db_upgrade
from io import BytesIO

from fhost import app, db, url_for, File, URL

@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as tmpdir:
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmpdir}/db.sqlite"
        app.config["FHOST_STORAGE_PATH"] = os.path.join(tmpdir, "up")
        app.config["TESTING"] = True

        with app.test_client() as client:
            with app.app_context():
                db_upgrade()
            yield client

def test_client(client):
    payloads = [
        ({ "file" : (BytesIO(b"hello"), "hello.txt") }, 200, b"https://localhost/E.txt\n"),
        ({ "file" : (BytesIO(b"hello"), "hello.ignorethis") }, 200, b"https://localhost/E.txt\n"),
        ({ "file" : (BytesIO(b"bye"), "bye.truncatethis") }, 200, b"https://localhost/Q.truncate\n"),
        ({ "file" : (BytesIO(b"hi"), "hi.tar.gz") }, 200, b"https://localhost/h.tar.gz\n"),
        ({ "file" : (BytesIO(b"lea!"), "lea!") }, 200, b"https://localhost/d.txt\n"),
        ({ "file" : (BytesIO(b"why?"), "balls", "application/x-dosexec") }, 415, None),
        ({ "shorten" : "https://0x0.st" }, 200, b"https://localhost/E\n"),
        ({ "shorten" : "https://localhost" }, 400, None),
        ({}, 400, None),
    ]

    for p, s, r in payloads:
        rv = client.post("/", buffered=True,
                        content_type="multipart/form-data",
                        data=p)
        assert rv.status_code == s
        if r:
            assert rv.data == r

    f = File.query.get(2)
    f.removed = True
    db.session.add(f)
    db.session.commit()

    rq = [
        (200, [
            "/",
            "robots.txt",
            "E.txt",
            "E.txt/test",
            "E.txt/test.py",
            "d.txt",
            "h.tar.gz",
        ]),
        (302, [
            "E",
            "E/test",
            "E/test.bin",
        ]),
        (404, [
            "test.bin",
            "test.bin/test",
            "test.bin/test.py",
            "test",
            "test/test",
            "test.bin/test.py",
            "E.bin",
        ]),
        (451, [
            "Q.truncate",
        ]),
    ]

    for code, paths in rq:
        for p in paths:
            app.logger.info(f"GET {p}")
            rv = client.get(p)
            assert rv.status_code == code

