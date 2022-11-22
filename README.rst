The Null Pointer
================

This is a no-bullshit file hosting and URL shortening service that also runs
`0x0.st <https://0x0.st>`_. Use with uWSGI.

Configuration
-------------

To configure 0x0, copy ``instance/config.example.py`` to ``instance/config.py``, then edit
it.   Resonable defaults are set, but there's a couple options you'll need to change
before running 0x0 for the first time.

By default, the configuration is stored in the Flask instance directory.
Normally, this is in `./instance`, but it might be different for your system.
For details, see
`the Flask documentation <https://flask.palletsprojects.com/en/2.0.x/config/#instance-folders>`_.

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
Otherwise, Flask will serve the file with chunked encoding, which has several
downsides, one of them being that range requests will not work. This is a
problem for example when streaming media files: It won’t be possible to seek,
and some ISOBMFF (MP4) files will not play at all.

To make files expire, simply create a cronjob that runs ``FLASK_APP=fhost
flask prune`` every now and then.

Before running the service for the first time, run ``FLASK_APP=fhost flask db upgrade``.


NSFW Detection
--------------

0x0 supports classification of NSFW content via Yahoo’s open_nsfw Caffe
neural network model. This works for images and video files and requires
the following:

* Caffe Python module (built for Python 3)
* ``ffmpegthumbnailer`` executable in ``$PATH``


Network Security Considerations
-------------------------------

Keep in mind that 0x0 can fetch files from URLs. This includes your local
network! You should take precautions so that this feature cannot be abused.
0x0 does not (yet) have a way to filter remote URLs, but on Linux, you can
use firewall rules and/or namespaces. This is less error-prone anyway.

For instance, if you are using the excellent `FireHOL <https://firehol.org/>`_,
it’s very easy to create a group on your system and use it as a condition
in your firewall rules. You would then run the application server under that
group.
