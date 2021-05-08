from test import process_client, assert_util, data as test_data
import pytest
from layman import app
from .. import util


@pytest.mark.usefixtures('ensure_layman')
def test_bbox():
    workspace = 'test_bbox_workspace'
    map = 'test_bbox_map'

    process_client.publish_workspace_map(workspace, map, )

    with app.app_context():
        info = util.get_map_info(workspace, map)
    assert_util.assert_same_bboxes(info['bounding_box'], test_data.SMALL_MAP_BBOX, 0.00001)

    process_client.patch_workspace_map(workspace, map, file_paths=['test/data/bbox/map_3_3-5_5.json', ])

    with app.app_context():
        info = util.get_map_info(workspace, map)
    assert_util.assert_same_bboxes(info['bounding_box'], [3000, 3000, 5000, 5000], 0.1)

    process_client.delete_workspace_map(workspace, map)
