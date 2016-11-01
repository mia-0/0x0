#!/usr/bin/env python3

import os, sys, time, datetime
from fhost import app

os.chdir(os.path.dirname(sys.argv[0]))
os.chdir(app.config["FHOST_STORAGE_PATH"])

files = [f for f in os.listdir(".")]

maxs = app.config["MAX_CONTENT_LENGTH"]
mind = 30
maxd = 365

for f in files:
    stat = os.stat(f)
    systime = time.time()
    age = datetime.timedelta(seconds = systime - stat.st_mtime).days

    maxage = mind + (-maxd + mind) * (stat.st_size / maxs - 1) ** 3

    if age >= maxage:
        os.remove(f)
