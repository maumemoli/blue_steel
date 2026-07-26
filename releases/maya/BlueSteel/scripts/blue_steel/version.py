import re


class InvalidVersion(ValueError):
    """Raised when a version string does not match PEP 440."""


class _Infinity(object):
    def __lt__(self, other):
        return False

    def __le__(self, other):
        return isinstance(other, _Infinity)

    def __eq__(self, other):
        return isinstance(other, _Infinity)

    def __ne__(self, other):
        return not isinstance(other, _Infinity)

    def __gt__(self, other):
        return not isinstance(other, _Infinity)

    def __ge__(self, other):
        return True

    def __repr__(self):
        return "Infinity"


class _NegativeInfinity(object):
    def __lt__(self, other):
        return not isinstance(other, _NegativeInfinity)

    def __le__(self, other):
        return True

    def __eq__(self, other):
        return isinstance(other, _NegativeInfinity)

    def __ne__(self, other):
        return not isinstance(other, _NegativeInfinity)

    def __gt__(self, other):
        return False

    def __ge__(self, other):
        return isinstance(other, _NegativeInfinity)

    def __repr__(self):
        return "-Infinity"


Infinity = _Infinity()
NegativeInfinity = _NegativeInfinity()


_VERSION_RE = re.compile(
    r"""^\s*v?
    (?:(?P<epoch>[0-9]+)!)?
    (?P<release>[0-9]+(?:\.[0-9]+)*)
    (?:(?:[-_.]?)
        (?P<pre_l>a|b|c|rc|alpha|beta|pre|preview)
        (?:[-_.]?(?P<pre_n>[0-9]+)?)
    )?
    (?:
        (?:-(?P<post_n1>[0-9]+))
        |
        (?:(?:[-_.]?)
            (?P<post_l>post|rev|r)
            (?:[-_.]?(?P<post_n2>[0-9]+)?)
        )
    )?
    (?:(?:[-_.]?)
        (?P<dev_l>dev)
        (?:[-_.]?(?P<dev_n>[0-9]+)?)
    )?
    (?:\+(?P<local>[a-z0-9]+(?:[-_.][a-z0-9]+)*))?
    \s*$""",
    re.VERBOSE | re.IGNORECASE,
)

_PRE_LABELS = {
    "a": "a",
    "alpha": "a",
    "b": "b",
    "beta": "b",
    "c": "rc",
    "rc": "rc",
    "pre": "rc",
    "preview": "rc",
}

_PRE_ORDER = {"a": 0, "b": 1, "rc": 2}


def _trim_trailing_zeros(parts):
    trimmed = list(parts)
    while trimmed and trimmed[-1] == 0:
        trimmed.pop()
    return tuple(trimmed) if trimmed else (0,)


def _parse_letter_version(label, number):
    if label is None:
        return None
    normalized_label = _PRE_LABELS.get(label.lower(), label.lower())
    normalized_number = int(number) if number is not None else 0
    return normalized_label, normalized_number


def _parse_local(local):
    if local is None:
        return None
    parts = re.split(r"[-_.]", local.lower())
    normalized = []
    for part in parts:
        if part.isdigit():
            normalized.append(int(part))
        else:
            normalized.append(part)
    return tuple(normalized)


def _local_key(local):
    if local is None:
        return NegativeInfinity

    key = []
    for part in local:
        if isinstance(part, int):
            key.append((1, part))
        else:
            key.append((0, part))
    return tuple(key)


class Version(object):
    """PEP 440 compatible version parser and comparator."""

    def __init__(self, version):
        version = str(version)
        match = _VERSION_RE.match(version)
        if not match:
            raise InvalidVersion("Invalid version: '{}'".format(version))

        self._version = version
        self.epoch = int(match.group("epoch")) if match.group("epoch") else 0
        self.release = tuple(int(i) for i in match.group("release").split("."))

        self.pre = _parse_letter_version(match.group("pre_l"), match.group("pre_n"))

        post_n1 = match.group("post_n1")
        post_n2 = match.group("post_n2")
        if post_n1 is not None:
            self.post = int(post_n1)
        elif match.group("post_l") is not None:
            self.post = int(post_n2) if post_n2 is not None else 0
        else:
            self.post = None

        if match.group("dev_l") is not None:
            self.dev = int(match.group("dev_n")) if match.group("dev_n") is not None else 0
        else:
            self.dev = None

        self.local = _parse_local(match.group("local"))
        self._key = self._cmp_key()

    def _cmp_key(self):
        release = _trim_trailing_zeros(self.release)

        if self.pre is None and self.post is None and self.dev is not None:
            pre = NegativeInfinity
        elif self.pre is None:
            pre = Infinity
        else:
            pre = (_PRE_ORDER[self.pre[0]], self.pre[1])

        post = NegativeInfinity if self.post is None else (self.post,)
        dev = Infinity if self.dev is None else (self.dev,)
        local = _local_key(self.local)

        return self.epoch, release, pre, post, dev, local

    @property
    def base_version(self):
        version = ".".join(str(i) for i in self.release)
        if self.epoch != 0:
            version = "{}!{}".format(self.epoch, version)
        return version

    @property
    def public(self):
        return str(self).split("+", 1)[0]

    @property
    def is_prerelease(self):
        return self.pre is not None or self.dev is not None

    @property
    def is_postrelease(self):
        return self.post is not None

    @property
    def is_devrelease(self):
        return self.dev is not None

    def __repr__(self):
        return "<Version('{}')>".format(str(self))

    def __str__(self):
        version = self.base_version

        if self.pre is not None:
            version += "{}{}".format(self.pre[0], self.pre[1])

        if self.post is not None:
            version += ".post{}".format(self.post)

        if self.dev is not None:
            version += ".dev{}".format(self.dev)

        if self.local is not None:
            local = ".".join(str(i) for i in self.local)
            version += "+{}".format(local)

        return version

    def __hash__(self):
        return hash(self._key)

    def _coerce(self, other):
        if isinstance(other, Version):
            return other
        return NotImplemented

    def __lt__(self, other):
        other = self._coerce(other)
        if other is NotImplemented:
            return NotImplemented
        return self._key < other._key

    def __le__(self, other):
        other = self._coerce(other)
        if other is NotImplemented:
            return NotImplemented
        return self._key <= other._key

    def __eq__(self, other):
        other = self._coerce(other)
        if other is NotImplemented:
            return NotImplemented
        return self._key == other._key

    def __ne__(self, other):
        other = self._coerce(other)
        if other is NotImplemented:
            return NotImplemented
        return self._key != other._key

    def __ge__(self, other):
        other = self._coerce(other)
        if other is NotImplemented:
            return NotImplemented
        return self._key >= other._key

    def __gt__(self, other):
        other = self._coerce(other)
        if other is NotImplemented:
            return NotImplemented
        return self._key > other._key
