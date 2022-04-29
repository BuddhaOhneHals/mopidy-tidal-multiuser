from __future__ import unicode_literals

import logging
import os
import json
from collections import namedtuple

from mopidy import backend

from pykka import ThreadingActor

from tidalapi import Config, Session, Quality

from . import library, playback, playlists, Extension


logger = logging.getLogger(__name__)


class TidalBackendConfig(namedtuple('TidalBackendConfig', 'quality client_id client_secret profiles')):
    def has_profiles(self):
        return len(self.profiles) > 0

    @property
    def default_profile(self):
        return self.profiles[0] if self.has_profiles() else None


class LegacyOAuthSessionDataFormat(Exception):
    pass


class TidalBackend(ThreadingActor, backend.Backend):
    def __init__(self, config, audio):
        super(TidalBackend, self).__init__()
        self._session = None
        self._config = config
        self.backend_config = self.validate_config(config['tidal'])
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

    def oauth_login_new_session(self, profile):
        # create a new session
        logger.info("Creating new OAuth session for %s", profile)
        self._session.login_oauth_simple(function=logger.info)
        if self._session.check_login():
            # store current OAuth session
            data = {
                'token_type': self._session.token_type,
                'session_id': self._session.session_id,
                'access_token': self._session.access_token,
                'refresh_token': self._session.refresh_token,
            }
            oauth_file = self.get_oauth_config_file_path(profile)
            with open(oauth_file, 'w') as outfile:
                json.dump(data, outfile)

    def transform_legacy_oauth_data_file(self, file_path):
        """Transform a file containing OAuth session data in a legacy format into the current format.

        :param str file_path: Path to the file containing the OAuth session data
        """
        with open(file_path) as f:
            data = json.load(f)
        transformed_data = {
            key: value['data'] for key, value in data.items()
        }
        with open(file_path, 'w') as outfile:
            json.dump(transformed_data, outfile)

    def get_oauth_config_file_path(self, profile=None):
        data_dir = Extension.get_data_dir(self._config)
        file_name = 'tidal-oauth-{}.json'.format(profile) if profile else 'tidal-oauth.json'
        return os.path.join(data_dir, file_name)

    def read_oauth_data_file(self, profile_file_path):
        logger.info("Loading OAuth session from %s.", profile_file_path)
        with open(profile_file_path) as f:
            data = json.load(f)
            # Check for incompatible (legacy) data structure
            if any(filter(lambda x: isinstance(x, dict), data.values())):
                raise LegacyOAuthSessionDataFormat()
            session_id = data['session_id']
            token_type = data['token_type']
            access_token = data['access_token']
            refresh_token = data['refresh_token']
        return session_id, token_type, access_token, refresh_token

    def try_login_with_existing_data(self):
        oauth_file = self.get_oauth_config_file_path(self.backend_config.default_profile)
        try:
            session_id, token_type, access_token, refresh_token = self.read_oauth_data_file(oauth_file)
        except OSError as exc:
            # An error occurred while reading the file (not existent, missing permissions, ...)
            logger.info('Cannot read OAuth session data from %s: %s', oauth_file, exc)
            return False
        except json.decoder.JSONDecodeError as exc:
            # The contents of the file couldn't be read as JSON data
            logger.warning('Cannot parse OAuth session data from %s: %s', oauth_file, exc)
            return False
        except LegacyOAuthSessionDataFormat:
            # The file contains OAuth session data in the old format, trying to transform it and retry the login
            logger.warning('Found legacy OAuth data structure, trying to transform it (%s)', oauth_file)
            self.transform_legacy_oauth_data_file(oauth_file)
            return self.try_login_with_existing_data()
        return self._session.load_oauth_session(session_id, token_type, access_token, refresh_token)

    def on_start(self):
        tidal_config = self.create_tidal_config(self.backend_config)
        self._session = Session(tidal_config)
        self.try_login_with_existing_data()

        if not self._session.check_login():
            self.oauth_login_new_session(self.backend_config.default_profile)

        if self._session.check_login():
            logger.info("TIDAL Login OK")
        else:
            logger.info("TIDAL Login KO")
