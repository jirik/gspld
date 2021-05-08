from test import process_client, assert_util, data as test_data
import pytest

from layman import app, settings
from layman.common.prime_db_schema import publications
from layman.http import LaymanError
from . import wfs, wms, tasks


@pytest.mark.usefixtures('ensure_layman')
def test_check_workspace_wms():
    workspace = 'test_check_workspace_wms_user' + settings.LAYMAN_GS_WMS_WORKSPACE_POSTFIX
    layer = 'test_check_workspace_wms_layer'
    with pytest.raises(LaymanError) as exc_info:
        process_client.publish_workspace_layer(workspace, layer)
    assert exc_info.value.http_code == 400
    assert exc_info.value.code == 45
    assert exc_info.value.data['workspace_name'] == workspace


@pytest.mark.usefixtures('ensure_layman', 'liferay_mock')
def test_check_user_wms():
    user = 'test_check_user_wms' + settings.LAYMAN_GS_WMS_WORKSPACE_POSTFIX
    auth_headers = process_client.get_authz_headers(user)
    with pytest.raises(LaymanError) as exc_info:
        process_client.reserve_username(user, headers=auth_headers)
    assert exc_info.value.http_code == 400
    assert exc_info.value.code == 45
    assert exc_info.value.data['workspace_name'] == user


@pytest.mark.usefixtures('ensure_layman')
def test_geoserver_bbox():
    workspace = 'test_geoserver_bbox_workspace'
    layer = 'test_geoserver_bbox_layer'
    expected_bbox_1 = test_data.SMALL_LAYER_BBOX
    expected_bboxes = [((1571203, 6268895, 1572589, 6269864), (1571203, 6268895, 1572589, 6269864)),
                       ((1571203, 6268895, 1571203, 6269864), (1571203 - settings.NO_AREA_BBOX_PADDING, 6268895,
                                                               1571203 + settings.NO_AREA_BBOX_PADDING, 6269864)),  # line
                       ((1571203, 6268895, 1571203, 6268895), (1571203 - settings.NO_AREA_BBOX_PADDING,
                                                               6268895 - settings.NO_AREA_BBOX_PADDING,
                                                               1571203 + settings.NO_AREA_BBOX_PADDING,
                                                               6268895 + settings.NO_AREA_BBOX_PADDING)),  # point
                       ((None, None, None, None), settings.LAYMAN_DEFAULT_OUTPUT_BBOX),
                       ]

    process_client.publish_workspace_layer(workspace, layer, style_file='sample/style/small_layer.qml')

    assert_util.assert_wfs_bbox(workspace, layer, expected_bbox_1)
    assert_util.assert_wms_bbox(workspace, layer, expected_bbox_1)

    # test WFS
    for bbox, expected_bbox in expected_bboxes:
        wfs.delete_layer(workspace, layer)
        with app.app_context():
            publications.set_bbox(workspace, process_client.LAYER_TYPE, layer, bbox)
            wfs.delete_layer(workspace, layer)
            tasks.refresh_wfs.apply(args=[workspace, layer],
                                    description=layer,
                                    title=layer,
                                    ensure_user=False,
                                    access_rights=None,
                                    )
        assert_util.assert_wfs_bbox(workspace, layer, expected_bbox)

    # test WMS
    for bbox, expected_bbox in expected_bboxes:
        wms.delete_layer(workspace, layer)
        with app.app_context():
            publications.set_bbox(workspace, process_client.LAYER_TYPE, layer, bbox)
            tasks.refresh_wms.apply(args=[workspace, layer, True],
                                    description=layer,
                                    title=layer,
                                    ensure_user=False,
                                    access_rights=None,
                                    )
        assert_util.assert_wms_bbox(workspace, layer, expected_bbox)

    # test cascade WMS from QGIS
    for bbox, expected_bbox in expected_bboxes:
        wms.delete_layer(workspace, layer)
        with app.app_context():
            publications.set_bbox(workspace, process_client.LAYER_TYPE, layer, bbox)
            wms.delete_layer(workspace, layer)
            tasks.refresh_wms.apply(args=[workspace, layer, False],
                                    description=layer,
                                    title=layer,
                                    ensure_user=False,
                                    access_rights=None,
                                    )
        assert_util.assert_wms_bbox(workspace, layer, expected_bbox)

    process_client.delete_workspace_layer(workspace, layer)
