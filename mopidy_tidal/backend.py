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

    @classmethod
    def from_dict(cls, config):
        """Create a :class:`TidalBackendConfig` instance.

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
        return cls(quality, client_id, client_secret, profiles)


class TidalBackend(ThreadingActor, backend.Backend):
    def __init__(self, config, audio):
        super(TidalBackend, self).__init__()
        self.authentication = None
        self._config = config
        self.backend_config = TidalBackendConfig.from_dict(config['tidal'])
        self.playback = playback.TidalPlaybackProvider(audio=audio,
                                                       backend=self)
        self.library = library.TidalLibraryProvider(backend=self)
        self.playlists = playlists.TidalPlaylistsProvider(backend=self)
        self.uri_schemes = ['tidal']

    @property
    def _session(self):
        # Helper for backwards compatibility
        return self.authentication.session

    @property
    def available_profiles(self):
        return self.backend_config.profiles

    @property
    def active_profile(self):
        return self.authentication.active_profile

    def has_profiles(self):
        return self.backend_config.has_profiles()

    def switch_profile(self, profile):
        is_logged_in = self.authentication.login(profile)
        return is_logged_in

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

    def on_authenticate(self, is_logged_in):
        if is_logged_in:
            logger.info("TIDAL Login OK")
            self.library.refresh()
            self.playlists.refresh()
        else:
            logger.info("TIDAL Login KO")

    def on_start(self):
        tidal_config = self.create_tidal_config(self.backend_config)
        self.authentication = TidalAuthentication(tidal_config, storage_path=Extension.get_data_dir(self._config),
                                                  callback=self.on_authenticate)
        self.authentication.login(self.backend_config.default_profile)
