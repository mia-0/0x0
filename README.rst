The Null Pointer
================

This is a no-bullshit file hosting and URL shortening service that also runs
`0x0.st <https://0x0.st>`_. Use with uWSGI.

If you are running nginx, you should use the ``X-Accel-Redirect`` header.
To make it work, include this in your nginx config’s ``server`` block::

    location /up {
        internal;
    }

where ``/up`` is whatever you’ve configured as ``FHOST_STORAGE_PATH``
in ``fhost.py``.

For all other servers, set ``FHOST_USE_X_ACCEL_REDIRECT`` to ``False`` and
``USE_X_SENDFILE`` to ``True``, assuming your server supports this.
Otherwise, Flask will serve the file with chunked encoding, which sucks and
should be avoided at all costs.

To make files expire, simply create a cronjob that runs ``cleanup.py`` every
now and then.

Before running the service for the first time, run ``./fhost.py db upgrade``.


FAQ
---

Q:
    Will you ever add a web interface with HTML forms?
A:
    No. This would without a doubt make it very popular and quickly exceed
    my hosting budget unless I started crippling it.

Q:
    What about file management? Will I be able to register an account at some
    point?
A:
    No.

Q:
    Why are you storing IP addresses with each uploaded file?
A:
    This is done to make dealing with legal claims and accidental uploads
    easier, e.g. when a user requests removal of all text files uploaded from
    a certain address within a given time frame (it happens).

Q:
    Do you accept donations?
A:
    Only if you insist. I’ve spent very little time and effort on this service
    and I don’t feel like I should be taking money for it.
