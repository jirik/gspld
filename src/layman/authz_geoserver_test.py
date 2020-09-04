import os
import pytest
import importlib
from multiprocessing import Process
import time
import requests
from requests.exceptions import ConnectionError
import subprocess
from test.mock.liferay import run
from layman import settings
from layman.common import geoserver


settings = importlib.import_module(os.environ['LAYMAN_SETTINGS_MODULE'])

LIFERAY_PORT = 8020

SUBPROCESSES = set()
ISS_URL_HEADER = 'AuthorizationIssUrl'
TOKEN_HEADER = 'Authorization'

AUTHN_INTROSPECTION_URL = f"http://{settings.LAYMAN_SERVER_NAME.split(':')[0]}:{LIFERAY_PORT}/rest/test-oauth2/introspection?is_active=true"

AUTHN_SETTINGS = {
    'LAYMAN_AUTHN_MODULES': 'layman.authn.oauth2',
    'OAUTH2_LIFERAY_INTROSPECTION_URL': AUTHN_INTROSPECTION_URL,
    'OAUTH2_LIFERAY_USER_PROFILE_URL': f"http://{settings.LAYMAN_SERVER_NAME.split(':')[0]}:{LIFERAY_PORT}/rest/test-oauth2/user-profile",
}

LAYMAN_CELERY_QUEUE = 'temporary'


def wait_for_url(url, max_attempts, sleeping_time):
    attempt = 1
    while True:
        # print(f"Waiting for URL {url}, attempt {attempt}")
        try:
            r = requests.get(url)
            break
        except ConnectionError as e:
            if attempt == max_attempts:
                print(f"Max attempts reached")
                raise e
            attempt += 1
        time.sleep(sleeping_time)


@pytest.fixture(scope="module")
def liferay_mock():
    server = Process(target=run, kwargs={
        'env_vars': {
        },
        'app_config': {
            'ENV': 'development',
            'SERVER_NAME': f"{settings.LAYMAN_SERVER_NAME.split(':')[0]}:{LIFERAY_PORT}",
            'SESSION_COOKIE_DOMAIN': f"{settings.LAYMAN_SERVER_NAME.split(':')[0]}:{LIFERAY_PORT}",
            'OAUTH2_USERS': {
                'test_rewe1': None,
                'test_rewo1': None,
                'test_rewe_rewo1': None,
                'test_rewe_rewo2': None,
                'testproxy': None,
            },
        },
        'host': '0.0.0.0',
        'port': LIFERAY_PORT,
        'debug': True,  # preserve error log in HTTP responses
        'load_dotenv': False,
        'options': {
            'use_reloader': False,
        },
    })
    server.start()
    wait_for_url(AUTHN_INTROSPECTION_URL, 20, 0.1)

    yield server

    server.terminate()
    server.join()


@pytest.fixture(scope="module", autouse=True)
def clear():
    yield
    while len(SUBPROCESSES) > 0:
        proc = next(iter(SUBPROCESSES))
        stop_process(proc)


def start_layman(env_vars=None):
    # first flush redis DB
    settings.LAYMAN_REDIS.flushdb()
    port = settings.LAYMAN_SERVER_NAME.split(':')[1]
    env_vars = env_vars or {}

    layman_env = os.environ.copy()
    layman_env.update(**env_vars)
    layman_env['LAYMAN_CELERY_QUEUE'] = LAYMAN_CELERY_QUEUE
    cmd = f'flask run --host=0.0.0.0 --port={port} --no-reload'
    layman_process = subprocess.Popen(cmd.split(), shell=False, stdin=None, env=layman_env)

    SUBPROCESSES.add(layman_process)
    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/rest/current-user"
    wait_for_url(rest_url, 50, 0.1)

    celery_env = layman_env.copy()
    celery_env['LAYMAN_SKIP_REDIS_LOADING'] = 'true'
    cmd = f'python3 -m celery -Q {LAYMAN_CELERY_QUEUE} -A layman.celery_app worker --loglevel=info'
    celery_process = subprocess.Popen(cmd.split(), shell=False, stdin=None, env=layman_env, cwd='src')

    SUBPROCESSES.add(celery_process)

    return layman_process, celery_process


def stop_process(process):
    if type(process) is not tuple:
        process = (process,)
    for proc in process:
        proc.kill()
        SUBPROCESSES.remove(proc)


def publish_layer(username, layername, file_paths, headers=None):
    headers = headers or {}
    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/rest"

    r_url = f"{rest_url}/{username}/layers"
    for fp in file_paths:
        assert os.path.isfile(fp)
    files = []
    try:
        r = requests.post(r_url, files=[
            ('file', (os.path.basename(fp), open(fp, 'rb')))
            for fp in file_paths
        ], data={
            'name': layername,
        }, headers=headers)
        assert r.status_code == 200, r.text
    finally:
        for fp in files:
            fp[0].close()

    r_url = f"{rest_url}/{username}/layers/{layername}"
    r = requests.get(r_url)
    keys_to_check = ['db_table', 'wms', 'wfs', 'thumbnail', 'file', 'metadata']
    max_attempts = 20
    attempts = 1
    while not (r.status_code == 200 and all(
            'status' not in r.json()[k] for k in keys_to_check
    )):
        time.sleep(0.5)
        r = requests.get(r_url)
        attempts += 1
        if attempts > max_attempts:
            raise Exception('Max attempts reached!')
    return layername


def patch_layer(username, layername, file_paths, headers=None):
    headers = headers or {}
    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/rest"

    r_url = f"{rest_url}/{username}/layers/{layername}"
    for fp in file_paths:
        assert os.path.isfile(fp)
    files = []
    try:
        r = requests.patch(r_url, files=[
            ('file', (os.path.basename(fp), open(fp, 'rb')))
            for fp in file_paths
        ], headers=headers)
        assert r.status_code == 200, r.text
    finally:
        for fp in files:
            fp[0].close()

    r_url = f"{rest_url}/{username}/layers/{layername}"
    r = requests.get(r_url)
    keys_to_check = ['db_table', 'wms', 'wfs', 'thumbnail', 'file', 'metadata']
    max_attempts = 20
    attempts = 1
    while not (r.status_code == 200 and all(
            'status' not in r.json()[k] for k in keys_to_check
    )):
        time.sleep(0.5)
        r = requests.get(r_url)
        attempts += 1
        if attempts > max_attempts:
            raise Exception('Max attempts reached!')
    return layername


def delete_layer(username, layername, headers=None):
    headers = headers or {}
    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/rest"

    r_url = f"{rest_url}/{username}/layers/{layername}"
    r = requests.delete(r_url, headers=headers)
    assert r.status_code == 200, r.text


def assert_user_layers(username, layernames):
    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/rest"
    r_url = f"{rest_url}/{username}/layers"
    r = requests.get(r_url)
    assert r.status_code == 200, f"r.status_code={r.status_code}\n{r.text}=r.text"
    layman_names = [li['name'] for li in r.json()]
    assert set(layman_names) == set(layernames), f"{r.text}=r.text"


def reserve_username(username, headers=None):
    headers = headers or {}
    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/rest"
    r_url = f"{rest_url}/current-user?adjust_username=true"
    r = requests.patch(r_url, headers=headers)
    assert r.status_code == 200, r.text
    claimed_username = r.json()['username']
    assert claimed_username == username


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

    layman_process = start_layman(dict({
        'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_everyone',
    }, **AUTHN_SETTINGS))
    authn_headers1 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {test_user1}',
    }
    reserve_username(test_user1, headers=authn_headers1)
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewe_data_security(test_user1)

    ln = publish_layer(test_user1, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers1)
    assert ln == layername1
    assert_user_layers(test_user1, [layername1])
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewe_data_security(test_user1)

    delete_layer(test_user1, layername1, headers=authn_headers1)

    stop_process(layman_process)


def test_rewo(liferay_mock):
    test_user1 = 'test_rewo1'
    layername1 = 'layer1'
    layman_process = start_layman(dict({
        'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_owner',
    }, **AUTHN_SETTINGS))
    authn_headers2 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {test_user1}',
    }
    reserve_username(test_user1, headers=authn_headers2)
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewo_data_security(test_user1)

    ln = publish_layer(test_user1, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers2)
    assert ln == layername1
    assert_user_layers(test_user1, [layername1])
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewo_data_security(test_user1)

    delete_layer(test_user1, layername1, headers=authn_headers2)

    stop_process(layman_process)


def test_rewe_rewo(liferay_mock):
    test_user1 = 'test_rewe_rewo1'
    layername1 = 'layer1'

    layman_process = start_layman(dict({
        'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_everyone',
    }, **AUTHN_SETTINGS))

    authn_headers1 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {test_user1}',
    }
    reserve_username(test_user1, headers=authn_headers1)
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewe_data_security(test_user1)
    custom_role = 'CUSTOM_ROLE'
    auth = settings.LAYMAN_GS_AUTH
    assert geoserver.ensure_role(custom_role, auth)
    assert geoserver.ensure_user_role(test_user1, custom_role, auth)
    assert custom_role in geoserver.get_user_roles(test_user1, auth)

    ln = publish_layer(test_user1, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers1)
    assert ln == layername1
    assert_user_layers(test_user1, [layername1])
    assert_gs_user_and_roles(test_user1)
    assert_gs_rewe_data_security(test_user1)

    stop_process(layman_process)

    test_user2 = 'test_rewe_rewo2'
    layername2 = 'layer2'
    layman_process = start_layman(dict({
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
    patch_layer(test_user1, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers1)
    with pytest.raises(AssertionError):
        patch_layer(test_user1, layername1, [
            'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
        ], headers=authn_headers2)

    reserve_username(test_user2, headers=authn_headers2)
    assert_gs_user_and_roles(test_user2)
    assert_gs_rewo_data_security(test_user2)

    ln = publish_layer(test_user2, layername2, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers2)
    assert ln == layername2
    assert_user_layers(test_user2, [layername2])
    assert_gs_user_and_roles(test_user2)
    assert_gs_rewo_data_security(test_user2)

    patch_layer(test_user2, layername2, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers2)
    with pytest.raises(AssertionError):
        patch_layer(test_user2, layername2, [
            'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
        ], headers=authn_headers1)

    delete_layer(test_user1, layername1, headers=authn_headers1)
    delete_layer(test_user2, layername2, headers=authn_headers2)

    stop_process(layman_process)


def test_wfs_proxy(liferay_mock):
    username = 'testproxy'
    layername1 = 'ne_countries'
    layman_process = start_layman(dict({
        'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_owner',
        # 'LAYMAN_AUTHZ_MODULE': 'layman.authz.read_everyone_write_everyone',
    }, **AUTHN_SETTINGS))

    roles = set(geoserver.get_workspace_security_roles("testproxy", "w", settings.LAYMAN_GS_AUTH))
    print(f"Test1 roles={roles}")

    authn_headers1 = {
        f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
        f'{TOKEN_HEADER}': f'Bearer {username}',
    }
    roles = set(geoserver.get_workspace_security_roles("testproxy", "w", settings.LAYMAN_GS_AUTH))
    print(f"Test2 roles={roles}")

    reserve_username(username, headers=authn_headers1)

    roles = set(geoserver.get_workspace_security_roles("testproxy", "w", settings.LAYMAN_GS_AUTH))
    print(f"Test3 roles={roles}")

    ln = publish_layer(username, layername1, [
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers1)

    assert ln == layername1

    roles = set(geoserver.get_workspace_security_roles("testproxy", "w", settings.LAYMAN_GS_AUTH))
    print(f"Test4 roles={roles}")

    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/{username}/wfs?request=Transaction"
    headers = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
        **authn_headers1,
    }

    data_xml = f'''<?xml version="1.0"?>
    <wfs:Transaction
       version="2.0.0"
       service="WFS"
       xmlns:{username}="http://{username}"
       xmlns:fes="http://www.opengis.net/fes/2.0"
       xmlns:gml="http://www.opengis.net/gml/3.2"
       xmlns:wfs="http://www.opengis.net/wfs/2.0"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.opengis.net/wfs/2.0
                           http://schemas.opengis.net/wfs/2.0/wfs.xsd
                           http://www.opengis.net/gml/3.2
                           http://schemas.opengis.net/gml/3.2.1/gml.xsd">
       <wfs:Insert>
           <{username}:{layername1}>
               <{username}:wkb_geometry>
                   <gml:Point srsName="urn:ogc:def:crs:EPSG::3857" srsDimension="2">
                       <gml:pos>1.27108004304E7 2548415.5977</gml:pos>
                   </gml:Point>
               </{username}:wkb_geometry>
           </{username}:{layername1}>
       </wfs:Insert>
    </wfs:Transaction>'''

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    roles = set(geoserver.get_workspace_security_roles("testproxy", "w", settings.LAYMAN_GS_AUTH))
    print(f"Test5 roles={roles}")

    stop_process(layman_process)
