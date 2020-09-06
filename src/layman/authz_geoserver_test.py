import os
import pytest
import importlib
import requests

from src.layman import settings
from src.layman.common import geoserver

from test import process, client as client_util


settings = importlib.import_module(os.environ['LAYMAN_SETTINGS_MODULE'])

liferay_mock = process.liferay_mock

LIFERAY_PORT = process.LIFERAY_PORT

ISS_URL_HEADER = client_util.ISS_URL_HEADER
TOKEN_HEADER = client_util.TOKEN_HEADER

AUTHN_INTROSPECTION_URL = f"http://{settings.LAYMAN_SERVER_NAME.split(':')[0]}:{LIFERAY_PORT}/rest/test-oauth2/introspection?is_active=true"

AUTHN_SETTINGS = {
    'LAYMAN_AUTHN_MODULES': 'layman.authn.oauth2',
    'OAUTH2_LIFERAY_INTROSPECTION_URL': AUTHN_INTROSPECTION_URL,
    'OAUTH2_LIFERAY_USER_PROFILE_URL': f"http://{settings.LAYMAN_SERVER_NAME.split(':')[0]}:{LIFERAY_PORT}/rest/test-oauth2/user-profile",
}


def assert_gs_user_and_roles(username):
    auth = settings.LAYMAN_GS_AUTH
    gs_usernames = geoserver.get_usernames(auth)
    assert username in gs_usernames
    gs_user_roles = geoserver.get_user_roles(username, auth)
    user_role = f"USER_{username.upper()}"
    assert user_role in gs_user_roles
    assert settings.LAYMAN_GS_ROLE in gs_user_roles


def assert_gs_rewe_data_security(username):
    auth = settings.LAYMAN_GS_AUTH
    user_role = f"USER_{username.upper()}"
    gs_roles = geoserver.get_workspace_security_roles(username, 'r', auth)
    assert settings.LAYMAN_GS_ROLE in gs_roles
    assert 'ROLE_ANONYMOUS' in gs_roles
    assert 'ROLE_AUTHENTICATED' in gs_roles
    gs_roles = geoserver.get_workspace_security_roles(username, 'w', auth)
    assert settings.LAYMAN_GS_ROLE in gs_roles
    assert 'ROLE_ANONYMOUS' in gs_roles
    assert 'ROLE_AUTHENTICATED' in gs_roles


def assert_gs_rewo_data_security(username):
    auth = settings.LAYMAN_GS_AUTH
    user_role = f"USER_{username.upper()}"
    gs_roles = geoserver.get_workspace_security_roles(username, 'r', auth)
    assert settings.LAYMAN_GS_ROLE in gs_roles
    assert 'ROLE_ANONYMOUS' in gs_roles
    assert 'ROLE_AUTHENTICATED' in gs_roles
    gs_roles = geoserver.get_workspace_security_roles(username, 'w', auth)
    assert user_role in gs_roles
    assert 'ROLE_ANONYMOUS' not in gs_roles
    assert 'ROLE_AUTHENTICATED' not in gs_roles


def test_rewe(liferay_mock):
    test_user1 = 'test_rewe1'
    layername1 = 'layer1'

    layman_process = process.start_layman(dict({
        'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_everyone',
    }, **AUTHN_SETTINGS))
    authn_headers1 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {test_user1}',
    }
    client_util.reserve_username(test_user1, headers=authn_headers1)
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewe_data_security(test_user1)

    ln = client_util.publish_layer(test_user1, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers1)
    assert ln == layername1
    client_util.assert_user_layers(test_user1, [layername1])
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewe_data_security(test_user1)

    client_util.delete_layer(test_user1, layername1, headers=authn_headers1)

    process.stop_process(layman_process)


def test_rewo(liferay_mock):
    test_user1 = 'test_rewo1'
    layername1 = 'layer1'
    layman_process = process.start_layman(dict({
        'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_owner',
    }, **AUTHN_SETTINGS))
    authn_headers2 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {test_user1}',
    }
    client_util.reserve_username(test_user1, headers=authn_headers2)
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewo_data_security(test_user1)

    ln = client_util.publish_layer(test_user1, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers2)
    assert ln == layername1
    client_util.assert_user_layers(test_user1, [layername1])
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewo_data_security(test_user1)

    client_util.delete_layer(test_user1, layername1, headers=authn_headers2)

    process.stop_process(layman_process)


def test_rewe_rewo(liferay_mock):
    test_user1 = 'test_rewe_rewo1'
    layername1 = 'layer1'

    layman_process = process.start_layman(dict({
        'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_everyone',
    }, **AUTHN_SETTINGS))

    authn_headers1 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {test_user1}',
    }
    client_util.reserve_username(test_user1, headers=authn_headers1)
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewe_data_security(test_user1)
    custom_role = 'CUSTOM_ROLE'
    auth = settings.LAYMAN_GS_AUTH
    assert geoserver.ensure_role(custom_role, auth)
    assert geoserver.ensure_user_role(test_user1, custom_role, auth)
    assert custom_role in geoserver.get_user_roles(test_user1, auth)

    ln = client_util.publish_layer(test_user1, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers1)
    assert ln == layername1
    client_util.assert_user_layers(test_user1, [layername1])
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewe_data_security(test_user1)

    process.stop_process(layman_process)

    test_user2 = 'test_rewe_rewo2'
    layername2 = 'layer2'
    layman_process = process.start_layman(dict({
        'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_owner',
    }, **AUTHN_SETTINGS))
    authn_headers2 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {test_user2}',
    }

    assert_gs_user_and_roles(test_user1)
    assert_gs_rewo_data_security(test_user1)
    assert custom_role in geoserver.get_user_roles(test_user1, auth)
    assert geoserver.delete_user_role(test_user1, custom_role, auth)
    assert geoserver.delete_role(custom_role, auth)
    client_util.patch_layer(test_user1, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers1)
    with pytest.raises(AssertionError):
        client_util.patch_layer(test_user1, layername1, [
            'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
        ], headers=authn_headers2)

    client_util.reserve_username(test_user2, headers=authn_headers2)
    assert_gs_user_and_roles(test_user2)
    assert_gs_rewo_data_security(test_user2)

    ln = client_util.publish_layer(test_user2, layername2, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers2)
    assert ln == layername2
    client_util.assert_user_layers(test_user2, [layername2])
    assert_gs_user_and_roles(test_user2)
    assert_gs_rewo_data_security(test_user2)

    client_util.patch_layer(test_user2, layername2, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers2)
    with pytest.raises(AssertionError):
        client_util.patch_layer(test_user2, layername2, [
            'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
        ], headers=authn_headers1)

    client_util.delete_layer(test_user1, layername1, headers=authn_headers1)
    client_util.delete_layer(test_user2, layername2, headers=authn_headers2)

    process.stop_process(layman_process)


def test_wfs_proxy(liferay_mock):
    username = 'testproxy'
    layername1 = 'ne_countries'
    username2 = 'testproxy2'

    layman_process = process.start_layman(dict({
        'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_owner',
        # 'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_everyone',
    }, **AUTHN_SETTINGS))

    authn_headers1 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {username}',
    }

    client_util.reserve_username(username, headers=authn_headers1)
    ln = client_util.publish_layer(username, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers1)

    assert ln == layername1

    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/{username}/wfs?request=Transaction"
    headers = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
        **authn_headers1,
    }

    data_xml = client_util.get_wfs_insert_points(username, layername1)

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    # Testing, that user2 is not able to write to layer of user1
    authn_headers2 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {username2}',
    }

    headers2 = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
        **authn_headers2,
    }

    client_util.reserve_username(username2, headers=authn_headers2)

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers2)
    assert r.status_code == 400

    # Test anonymous
    headers3 = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
    }

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers3)
    assert r.status_code == 400

    process.stop_process(layman_process)
