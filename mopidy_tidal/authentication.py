import json
import logging
import os

from tidalapi import Session

logger = logging.getLogger(__name__)


class LegacyOAuthSessionDataFormat(Exception):
    pass


class TidalAuthentication:
    def __init__(self, tidal_config, storage_path=None):
        self.storage_path = storage_path
        self.tidal_config = tidal_config
        self.session = Session(tidal_config)

    def oauth_login_new_session(self, profile):
        # create a new session
        logger.info("Creating new OAuth session for %s", profile)
        self.session.login_oauth_simple(function=logger.info)
        if self.session.check_login():
            # store current OAuth session
            data = {
                'token_type': self.session.token_type,
                'session_id': self.session.session_id,
                'access_token': self.session.access_token,
                'refresh_token': self.session.refresh_token,
            }
            oauth_file = self.get_config_file_path(profile)
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

    def get_config_file_path(self, profile=None):
        file_name = 'tidal-oauth-{}.json'.format(profile) if profile else 'tidal-oauth.json'
        return os.path.join(self.storage_path, file_name)

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

    def try_login_with_existing_data(self, profile):
        oauth_file = self.get_config_file_path(profile)
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
        return self.session.load_oauth_session(session_id, token_type, access_token, refresh_token)
