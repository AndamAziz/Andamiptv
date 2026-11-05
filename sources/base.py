"""Source adapter interface. A source returns ONLY content whose license permits streaming/distribution; the engine then
re-validates every candidate (format, https, resolution, length, TMDB, duplicates, live link)."""


class Source:
    name = "base"
    # licenses this source may hand over (anything else is rejected by validate_source_candidate)
    allowed_licenses = ()
    distribution_policy = "describe here why the content may be streamed/distributed"

    def discover(self, opts):
        """Yield ('candidate', dict) or ('reject', {'title':..., 'reason':...}).
        A candidate dict has: source, sid, title, year, url, fmt, width, height, minutes, mb, license, logo, subjects, downloads."""
        raise NotImplementedError

    @staticmethod
    def candidate(**kw):
        base = dict(source="", sid="", title="", year="", url="", fmt="", width=0, height=0, minutes=0.0, mb=0,
                    license="", logo="", subjects=[], downloads=0)
        base.update(kw)
        return base
