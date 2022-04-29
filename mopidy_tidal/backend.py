from __future__ import unicode_literals

import logging
import os
import json
from collections import namedtuple

from mopidy import backend

from pykka import ThreadingActor

from tidalapi import Config, Session, Quality

from . import library, playback, playlists, Extension
from .authentication import TidalAuthentication

logger = logging.getLogger(__name__)


class TidalBackendConfig(namedtuple('TidalBackendConfig', 'quality client_id client_secret profiles')):
    def has_profiles(self):
        return len(self.profiles) > 0

    @property
    def default_profile(self):
        return self.profiles[0] if self.has_profiles() else None


class TidalBackend(ThreadingActor, backend.Backend):
    def __init__(self, config, audio):
        super(TidalBackend, self).__init__()
        self._config = config
        self.backend_config = self.validate_config(config['tidal'])
        self.authentication = None
        self.playback = playback.TidalPlaybackProvider(audio=audio,
                                                       backend=self)
        self.library = library.TidalLibraryProvider(backend=self)
        self.playlists = playlists.TidalPlaylistsProvider(backend=self)
        self.uri_schemes = ['tidal']

    @property
    def _session(self):
        # Helper for backwards compatibility
        return self.authentication.session

    def validate_config(self, config):
        """Validate the provided config and return a :class:`TidalBackendConfig` instance.

        :param dict config: A dictionary containing the configuration
        :returns: A validated configuration
        :rtype: TidalBackendConfig
        """
        quality = Quality(config['quality'])
        client_id = config['client_id']
        client_secret = config['client_secret']
        profiles = config['profiles']
        if client_id and client_secret:
            logger.info("client_id & client_secret from config section are used.")
        else:
            if client_id or client_secret:
                logger.warning("Always provide client_id and client_secret together")
            logger.info("Using default client id & client secret from python-tidal")
        return TidalBackendConfig(quality, client_id, client_secret, profiles)

    def create_tidal_config(self, config):
        """Create a tidalapi :class:`tidalapi.Config` object from the given configuration.

        :param TidalBackendConfig config: The configuration
        """
        tidal_config = Config(quality=config.quality)
        if config.client_id and config.client_secret:
            tidal_config.client_secret = config.client_secret
            tidal_config.client_id = config.client_id
            tidal_config.api_token = config.client_id
        return tidal_config

    def on_start(self):
        tidal_config = self.create_tidal_config(self.backend_config)
        self.authentication = TidalAuthentication(tidal_config, storage_path=Extension.get_data_dir(self._config))
        self.authentication.try_login_with_existing_data(self.backend_config.default_profile)

        if not self._session.check_login():
            self.authentication.oauth_login_new_session(self.backend_config.default_profile)

        if self._session.check_login():
            logger.info("TIDAL Login OK")
        else:
            logger.info("TIDAL Login KO")
