import time

from test import process_client, assert_util
from test.data import wfs as data_wfs
import requests
import pytest

from layman import celery, settings
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

    process_client.publish_workspace_layer(workspace, layer, )

    queue = celery.get_run_after_chain_queue(workspace, process_client.LAYER_TYPE, layer)
    assert not queue

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    queue = celery.get_run_after_chain_queue(workspace, process_client.LAYER_TYPE, layer)
    assert len(queue) == 0, queue

    process_client.patch_workspace_layer(workspace, layer, title='New title', check_response_fn=empty_method_returns_true)
    queue = celery.get_run_after_chain_queue(workspace, process_client.LAYER_TYPE, layer)
    assert len(queue) == 1, queue
    assert queue == ['layman.util::patch_after_wfst', ]

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    queue = celery.get_run_after_chain_queue(workspace, process_client.LAYER_TYPE, layer)
    assert len(queue) == 1, queue
    assert queue == ['layman.util::patch_after_wfst', ]

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    queue = celery.get_run_after_chain_queue(workspace, process_client.LAYER_TYPE, layer)
    assert len(queue) == 1, queue
    assert queue == ['layman.util::patch_after_wfst', ]

    time.sleep(3)

    expected_bbox = (1571000.0, 6268800.0, 1572590.8542062, 6269876.33561699)
    assert_util.assert_all_sources_bbox(workspace, layer, expected_bbox)

    process_client.delete_workspace_layer(workspace, layer, )

    queue = celery.get_run_after_chain_queue(workspace, process_client.LAYER_TYPE, layer)
    assert not queue, queue
