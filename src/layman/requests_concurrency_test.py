from test import process_client
from test.data import wfs as data_wfs
import requests
import pytest

from layman import settings
from layman.common import empty_method_returns_true


@pytest.mark.usefixtures('ensure_layman')
def test_wfst_concurrency():
    workspace = 'test_wfst_concurrency_workspace'
    layer = 'test_wfst_concurrency_layer'

    data_xml = data_wfs.get_wfs20_insert_points(workspace, layer, )
    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/{workspace}/wfs?request=Transaction"
    headers = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
    }

    process_client.publish_workspace_layer(workspace, layer,)

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    process_client.patch_workspace_layer(workspace, layer, title='New title', check_response_fn=empty_method_returns_true)

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    process_client.delete_workspace_layer(workspace, layer, )
