from __future__ import unicode_literals

import logging
import operator

from mopidy import backend
from mopidy.models import Playlist, Ref

from mopidy_tidal import full_models_mappers

logger = logging.getLogger(__name__)


class TidalPlaylistsProvider(backend.PlaylistsProvider):

    def __init__(self, *args, **kwargs):
        super(TidalPlaylistsProvider, self).__init__(*args, **kwargs)
        self._playlists = None

    def as_list(self):
        if self._playlists is None:
            self.refresh()

        logger.debug("Listing TIDAL playlists..")
        refs = [
            Ref.playlist(uri=pl.uri, name=pl.name)
            for pl in self._playlists.values()]
        return sorted(refs, key=operator.attrgetter('name'))

    def get_items(self, uri):
        logger.info("Get items for playlist: %s", uri)
        if self._playlists is None:
            self.refresh()

        playlist = self._playlists.get(uri)
        if playlist is None:
            return None
        return [Ref.track(uri=t.uri, name=t.name) for t in playlist.tracks]

    def create(self, name):
        pass  # TODO

    def delete(self, uri):
        pass  # TODO

    def lookup(self, uri):
        logger.info("Lookup playlist: %s", uri)
        return self._playlists.get(uri)

    def refresh(self):
        logger.debug("Refreshing TIDAL playlists..")
        playlists = {}
        session = self.backend._session

        plists = session.user.favorites.playlists()
        for pl in plists:
            pl.name = "* " + pl.name
        # Append favourites to end to keep the tagged name if there are
        # duplicates
        plists = session.user.playlists() + plists

        for pl in plists:
            uri = "tidal:playlist:" + pl.id
            pl_tracks = session.get_playlist_tracks(pl.id)
            tracks = full_models_mappers.create_mopidy_tracks(pl_tracks)
            playlists[uri] = Playlist(uri=uri,
                                      name=pl.name,
                                      tracks=tracks,
                                      last_modified=pl.last_updated)
        playlists.update(self.get_mixes_as_playlists())
        self._playlists = playlists
        backend.BackendListener.send('playlists_loaded')

    def get_mixes_as_playlists(self):
        """Return the mixes for a user as :class:`mopidy.models.Playlist` objects.

        :returns: A dict containing the mixes as :class:`mopidy.models.Playlist` objects (with the URI as key).
        :rtype: dict[str, Playlist]
        """
        playlists = {}
        session = self.backend._session
        rows = session.request('GET', 'pages/home', dict(deviceType='BROWSER')
                               ).json()['rows']
        for row in rows:
            for module in row.get('modules', []):
                if module['title'] != 'Mixes For You':
                    continue
                for mix in module['pagedList']['items']:
                    uri = "tidal:mix:" + mix['id']
                    tracks = self.backend.get_tracks_for_mix(mix['id'])
                    playlists[uri] = Playlist(uri=uri,
                                              name=mix['title'],
                                              tracks=tracks,
                                              last_modified=None)
        return playlists

    def save(self, playlist):
        pass  # TODO
