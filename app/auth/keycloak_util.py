# Copyright 2023-2024, CS GROUP - France, https://www.csgroup.eu/
#
# This file is part of APIKeyManager project
#     https://github.com/csgroup-oss/apikey-manager/
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import logging
from dataclasses import dataclass
from typing import Any

from keycloak import KeycloakAdmin, KeycloakError, KeycloakOpenIDConnection
from keycloak.exceptions import KeycloakGetError

from ..settings import api_settings as settings

LOGGER = logging.getLogger(__name__)


@dataclass
class KCInfo:
    is_enabled: bool
    roles: list[str]
    attributes: dict[str, Any]


class KCUtil:
    """
    Keycloak Admin API utility.

    Security note — get_user_info() is called by check_key() at a configurable
    interval (keycloak_sync_freq, default: 5 min) to re-verify that the user
    still exists and is active in Keycloak. This ensures that when an admin
    deletes or disables a user in Keycloak, their API keys stop working within
    the sync interval — even if the keys themselves haven't expired or been
    revoked. Without this sync, a deleted user's API keys would remain valid
    indefinitely.

    Connection endpoint — uses oidc_admin_endpoint (internal K8s DNS) for
    server-to-server Admin API calls, keeping traffic off the external network.
    The external oidc_endpoint is used only for JWT validation (issuer matching)
    and browser-facing OIDC flows.
    """

    def __get_keycloak_admin(self) -> KeycloakAdmin:
        """Init and return an admin keycloak connection from the admin client

        Uses settings.oidc_admin_endpoint (internal K8s DNS) rather than
        settings.oidc_endpoint (external), so Admin API calls stay on the
        cluster network.
        """
        endpoint = settings.oidc_admin_endpoint or settings.oidc_endpoint
        LOGGER.debug(f"Connecting to the keycloak admin server {endpoint} ...")
        try:
            keycloak_connection = KeycloakOpenIDConnection(
                server_url=endpoint,
                realm_name=settings.oidc_realm,
                client_id=settings.oidc_client_id,
                client_secret_key=settings.oidc_client_secret,
                verify=True,
            )
            LOGGER.debug("Connected to the keycloak server")
            return KeycloakAdmin(connection=keycloak_connection)

        except KeycloakError as error:
            raise RuntimeError(
                f"Error connecting with keycloak to '{endpoint}', "
                f"realm_name={settings.oidc_realm} with client_id="
                f"{settings.oidc_client_id}."
            ) from error

    def get_user_info(self, user_id: str) -> KCInfo:
        """Get user info from keycloak

        Creates a fresh Keycloak admin connection for each call to avoid
        stale TCP connection issues after idle periods (see class docstring).
        """
        try:
            kadm = self.__get_keycloak_admin()
            user = kadm.get_user(user_id)
            iam_roles = [
                role["name"] for role in kadm.get_composite_realm_roles_of_user(user_id)
            ]
            user_attributes = {
                attr: user.get("attributes", {}).get(attr)
                for attr in settings.oauth2_attributes
            }
            return KCInfo(user["enabled"], iam_roles, user_attributes)
        except KeycloakGetError as error:
            # If the user is not found, this means he was removed from keycloak.
            # Thus we must remove all his api keys from the database.
            if (error.response_code == 404) and (
                "User not found" in error.response_body.decode("utf-8")
            ):
                LOGGER.warning(f"User '{user_id}' not found in keycloak.")
                return KCInfo(False, [], {})

            raise