from __future__ import unicode_literals

import logging
import os
import sys
import json
from collections import namedtuple

from mopidy import backend

from pykka import ThreadingActor

from tidalapi import Config, Session, Quality

from mopidy_tidal import library, playback, playlists, Extension


logger = logging.getLogger(__name__)


class TidalBackendConfig(namedtuple('TidalBackendConfig', 'quality client_id client_secret profiles')):
    def has_profiles(self):
        return len(self.profiles) > 0

    @property
    def default_profile(self):
        return self.profiles[0] if self.has_profiles() else None


class TidalBackend(ThreadingActor, backend.Backend):
    def __init__(self, config, audio):
        logger.info('Bla')
        super(TidalBackend, self).__init__()
        self._session = None
        self._user_config = config['tidal']
        self.config = self.validate_config(config['tidal'])
        self.playback = playback.TidalPlaybackProvider(audio=audio,
                                                       backend=self)
        self.library = library.TidalLibraryProvider(backend=self)
        self.playlists = playlists.TidalPlaylistsProvider(backend=self)
        self.uri_schemes = ['tidal']

    def validate_config(self, config):
        """Validate the provided config and return a :class:`TidalBackendConfig` instance.

        :param dict config: A dictionary containing the configuration
        :returns: A validated configuration
        :rtype: TidalBackendConfig
        """
        quality = Quality(config['quantity'])
        client_id = config['client_id']
        client_secret = config['client_secret']
        profiles = config['profiles'].split(',') if config['profiles'] else []
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

    def oauth_login_new_session(self, oauth_file):
        # create a new session
        self._session.login_oauth_simple(function=logger.info)
        if self._session.check_login():
            # store current OAuth session
            data = {
                'token_type': self._session.token_type,
                'session_id': self._session.session_id,
                'access_token': self._session.access_token,
                'refresh_token': self._session.refresh_token,
            }
            with open(oauth_file, 'w') as outfile:
                json.dump(data, outfile)

    def get_oauth_config_file_path(self, profile='default'):
        data_dir = Extension.get_data_dir(self._user_config)
        return os.path.join(data_dir, 'tidal-oauth-{}.json'.format(profile))

    def on_start(self):
        tidal_config = self.create_tidal_config(self.config)
        self._session = Session(tidal_config)
        # Always store tidal-oauth cache in mopidy core config data_dir
        oauth_file = self.get_oauth_config_file_path(self.config.default_profile)
        try:
            # attempt to reload existing session from file
            with open(oauth_file) as f:
                logger.info("Loading OAuth session from %s.", oauth_file)
                data = json.load(f)
                self._session.load_oauth_session(
                    data['session_id'],
                    data['token_type'],
                    data['access_token'],
                    data['refresh_token'],
                )
        except:
            logger.info("Could not load OAuth session from %s" % oauth_file)

        if not self._session.check_login():
            logger.info("Creating new OAuth session...")
            self.oauth_login_new_session(oauth_file)

        if self._session.check_login():
            logger.info("TIDAL Login OK")
        else:
            logger.info("TIDAL Login KO")
