import requests
import os
import pytest
import time
from multiprocessing import Process

from layman import settings
from layman import app
from layman.layer.rest_test import wait_till_ready
from layman.util import url_for


ISS_URL_HEADER = 'AuthorizationIssUrl'
TOKEN_HEADER = 'Authorization'

layer_keys_to_check = ['db_table', 'wms', 'wfs', 'thumbnail', 'file', 'metadata']


def wait_for_rest(url, max_attempts, sleeping_time, keys_to_check):
    r = requests.get(url)

    attempts = 1
    while not (r.status_code == 200 and all(
            'status' not in r.json()[k] for k in keys_to_check
    )):
        time.sleep(sleeping_time)
        r = requests.get(url)
        attempts += 1
        if attempts > max_attempts:
            raise Exception('Max attempts reached!')


def publish_layer(username, layername, file_paths, headers=None):
    headers = headers or {}
    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/rest"

    r_url = f"{rest_url}/{username}/layers"
    for fp in file_paths:
        assert os.path.isfile(fp)
    files = []
    try:
        r = requests.post(r_url,
                          files=[('file', (os.path.basename(fp), open(fp, 'rb'))) for fp in file_paths],
                          data={'name': layername, },
                          headers=headers)
        assert r.status_code == 200, r.text
    finally:
        for fp in files:
            fp[0].close()

    wait_for_rest(f"{rest_url}/{username}/layers/{layername}", 20, 0.5, layer_keys_to_check)
    return layername


def setup_layer_flask(username, layername, client):
    with app.app_context():
        rest_path = url_for('rest_layers.post', username=username)

        file_paths = [
            'tmp/naturalearth/110m/cultural/ne_110m_populated_places.geojson',
        ]

        for fp in file_paths:
            assert os.path.isfile(fp)
        files = []

        try:
            files = [(open(fp, 'rb'), os.path.basename(fp)) for fp in file_paths]
            rv = client.post(rest_path, data={
                'file': files,
                'name': layername
            })
            assert rv.status_code == 200
        finally:
            for fp in files:
                fp[0].close()

    wait_till_ready(username, layername)


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

    wait_for_rest(f"{rest_url}/{username}/layers/{layername}", 20, 0.5, layer_keys_to_check)
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


@pytest.fixture()
def client():
    client = app.test_client()

    server = Process(target=app.run, kwargs={
        'host': '0.0.0.0',
        'port': settings.LAYMAN_SERVER_NAME.split(':')[1],
        'debug': False,
    })
    server.start()
    time.sleep(1)

    app.config['TESTING'] = True
    app.config['DEBUG'] = True
    app.config['SERVER_NAME'] = settings.LAYMAN_SERVER_NAME
    app.config['SESSION_COOKIE_DOMAIN'] = settings.LAYMAN_SERVER_NAME

    yield client

    server.terminate()
    server.join()
