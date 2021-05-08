from test import process_client, assert_util, data as test_data
import pytest
from layman import app
from .. import util


@pytest.mark.usefixtures('ensure_layman')
def test_bbox():
    workspace = 'test_bbox_workspace'
    layer = 'test_bbox_layer'

    process_client.publish_workspace_layer(workspace, layer, )

    with app.app_context():
        info = util.get_layer_info(workspace, layer)
    assert_util.assert_same_bboxes(info['bounding_box'], test_data.SMALL_LAYER_BBOX, 0.00001)

    process_client.patch_workspace_layer(workspace, layer, file_paths=['test/data/bbox/layer_3_3-5_5.geojson', ])

    with app.app_context():
        info = util.get_layer_info(workspace, layer)
    assert_util.assert_same_bboxes(info['bounding_box'], [3000, 3000, 5000, 5000], 0.1)

    process_client.delete_workspace_layer(workspace, layer)
