#!/usr/bin/env python3

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
