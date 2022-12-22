from enum import Enum
from textual import log

mimemoji = {
    "audio" : "🔈",
    "video" : "🎞",
    "text"  : "📄",
    "image" : "🖼",
    "application/zip" : "🗜️",
    "application/x-zip-compressed" : "🗜️",
    "application/x-tar" : "🗄",
    "application/x-cpio" : "🗄",
    "application/x-xz" : "🗜️",
    "application/x-7z-compressed" : "🗜️",
    "application/gzip" : "🗜️",
    "application/zstd" : "🗜️",
    "application/x-rar" : "🗜️",
    "application/x-rar-compressed" : "🗜️",
    "application/vnd.ms-cab-compressed" : "🗜️",
    "application/x-bzip2" : "🗜️",
    "application/x-lzip" : "🗜️",
    "application/x-iso9660-image" : "💿",
    "application/pdf" : "📕",
    "application/epub+zip" : "📕",
    "application/mxf" : "🎞",
    "application/vnd.android.package-archive" : "📦",
    "application/vnd.debian.binary-package" : "📦",
    "application/x-rpm" : "📦",
    "application/x-dosexec" : "⚙",
    "application/x-execuftable" : "⚙",
    "application/x-sharedlib" : "⚙",
    "application/java-archive" : "☕",
    "application/x-qemu-disk" : "🖴",
    "application/pgp-encrypted" : "🔏",
}

MIMECategory = Enum("MIMECategory",
    ["Archive", "Text", "AV", "Document", "Fallback"]
)

class MIMEHandler:
    def __init__(self):
        self.handlers = {
            MIMECategory.Archive : [[
                "application/zip",
                "application/x-zip-compressed",
                "application/x-tar",
                "application/x-cpio",
                "application/x-xz",
                "application/x-7z-compressed",
                "application/gzip",
                "application/zstd",
                "application/x-rar",
                "application/x-rar-compressed",
                "application/vnd.ms-cab-compressed",
                "application/x-bzip2",
                "application/x-lzip",
                "application/x-iso9660-image",
                "application/vnd.android.package-archive",
                "application/vnd.debian.binary-package",
                "application/x-rpm",
                "application/java-archive",
                "application/vnd.openxmlformats"
            ], []],
            MIMECategory.Text : [[
                "text",
                "application/json",
                "application/xml",
            ], []],
            MIMECategory.AV : [[
                "audio", "video", "image",
                "application/mxf"
            ], []],
            MIMECategory.Document : [[
                "application/pdf",
                "application/epub",
                "application/x-mobipocket-ebook",
            ], []],
            MIMECategory.Fallback : [[], []]
        }

        self.exceptions = {
            MIMECategory.Archive : {
                ".cbz" : MIMECategory.Document,
                ".xps" : MIMECategory.Document,
                ".epub" : MIMECategory.Document,
            },
            MIMECategory.Text : {
                ".fb2" : MIMECategory.Document,
            }
        }

    def register(self, category, handler):
        self.handlers[category][1].append(handler)

    def handle(self, mime, ext):
        def getcat(s):
            cat = MIMECategory.Fallback
            for k, v in self.handlers.items():
                s = s.split(";")[0]
                if s in v[0] or s.split("/")[0] in v[0]:
                    cat = k
                    break

                for x in v[0]:
                    if s.startswith(x):
                        cat = k
                        break

            if cat in self.exceptions:
                cat = self.exceptions[cat].get(ext) or cat

            return cat

        cat = getcat(mime)
        for handler in self.handlers[cat][1]:
            try:
                if handler(cat): return
            except: pass

        for handler in self.handlers[MIMECategory.Fallback][1]:
            try:
                if handler(None): return
            except: pass

        raise RuntimeError(f"Unhandled MIME type category: {cat}")
