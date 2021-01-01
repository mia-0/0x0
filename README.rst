The Null Pointer
================

This is a no-bullshit file hosting and URL shortening service that also runs
`0x0.st <https://0x0.st>`_. Use with uWSGI.

Configuration
-------------

To change settings, modify ``instance/config.py``. For more information on
instance configuration, see `the Flask documentation <https://flask.palletsprojects.com/en/2.0.x/config/#instance-folders>`_.

To customize the home and error pages, simply create a ``templates`` directory
in your instance directory and copy any templates you want to modify there.

If you are running nginx, you should use the ``X-Accel-Redirect`` header.
To make it work, include this in your nginx config’s ``server`` block::

    location /up {
        internal;
    }

where ``/up`` is whatever you’ve configured as ``FHOST_STORAGE_PATH``.

For all other servers, set ``FHOST_USE_X_ACCEL_REDIRECT`` to ``False`` and
``USE_X_SENDFILE`` to ``True``, assuming your server supports this.
Otherwise, Flask will serve the file with chunked encoding, which sucks and
should be avoided at all costs.

To make files expire, simply create a cronjob that runs ``cleanup.py`` every
now and then.

Before running the service for the first time, run ``FLASK_APP=fhost flask db upgrade``.


NSFW Detection
--------------

0x0 supports classification of NSFW content via Yahoo’s open_nsfw Caffe
neural network model. This works for images and video files and requires
the following:

* Caffe Python module (built for Python 3)
* ``ffmpegthumbnailer`` executable in ``$PATH``
