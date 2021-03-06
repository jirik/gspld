import json
import sys
from test import process_client
from test.util import url_for
import requests
import pytest

del sys.modules['layman']

from layman import app


@pytest.mark.usefixtures('ensure_layman')
def test_style_value():
    username = 'test_style_value_user'
    layername = 'test_style_value_layer'

    process_client.publish_workspace_layer(username, layername)

    with app.app_context():
        layer_url = url_for('rest_workspace_layer.get', workspace=username, layername=layername)
        expected_style_url = url_for('rest_workspace_layer_style.get', workspace=username, layername=layername,
                                     internal=False)
    r = requests.get(layer_url)
    assert r.status_code == 200, r.text
    resp_json = json.loads(r.text)

    assert 'style' in resp_json, r.text
    assert 'url' in resp_json['style'], r.text
    assert 'status' not in resp_json['style'], r.text

    external_style_url = resp_json['style']['url']
    assert external_style_url == expected_style_url, (r.text, external_style_url)

    with app.app_context():
        style_url = url_for('rest_workspace_layer_style.get', workspace=username, layername=layername)

    r_get = requests.get(style_url)
    assert r_get.status_code == 200, (r_get.text, style_url)

    r_del = requests.delete(style_url)
    assert r_del.status_code >= 400, (r_del.text, style_url)

    process_client.delete_workspace_layer(username, layername)
