import time
from test import process_client as client_util, geoserver_client, util as test_util
from test.process_client import get_authz_headers
from test.data import wfs as data_wfs, SMALL_LAYER_BBOX
import requests
from owslib.feature.schema import get_schema as get_wfs_schema
import pytest

from geoserver.util import get_layer_thumbnail, get_square_bbox
from layman import app, settings, util as layman_util
from layman.common import bbox as bbox_util
from layman.layer import db, util as layer_util
from layman.layer.filesystem import thumbnail
from layman.layer.geoserver import wfs as geoserver_wfs
from layman.layer.qgis import util as qgis_util, wms as qgis_wms


@pytest.mark.usefixtures('ensure_layman')
def test_rest_get():
    username = 'wfs_proxy_test'
    layername = 'layer_wfs_proxy_test'

    client_util.publish_workspace_layer(username, layername)

    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/{username}/wfs?request=Transaction"
    headers = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
    }

    data_xml = data_wfs.get_wfs20_insert_points(username, layername)

    with app.app_context():
        r = requests.post(rest_url,
                          data=data_xml,
                          headers=headers)
    assert r.status_code == 200, r.text

    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/wfs?request=GetCapabilities"
    with app.app_context():
        r = requests.post(rest_url,
                          headers=headers)
    assert r.status_code == 200

    client_util.delete_workspace_layer(username, layername)


def setup_user_layer(username, layername, authn_headers):
    client_util.reserve_username(username, headers=authn_headers)
    client_util.publish_workspace_layer(username, layername, file_paths=[
        'tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson',
    ], headers=authn_headers)


@pytest.mark.usefixtures('ensure_layman', 'liferay_mock')
def test_wfs_proxy():
    username = 'testproxy'
    layername1 = 'ne_countries'
    username2 = 'testproxy2'

    authn_headers1 = get_authz_headers(username)

    client_util.reserve_username(username, headers=authn_headers1)
    client_util.publish_workspace_layer(username,
                                        layername1,
                                        headers=authn_headers1)

    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/{username}/wfs?request=Transaction"
    headers = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
        **authn_headers1,
    }

    data_xml = data_wfs.get_wfs20_insert_points(username, layername1)

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    # Testing, that user1 is able to write his own layer through general WFS endpoint
    general_rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/wfs?request=Transaction"
    r = requests.post(general_rest_url,
                      data=data_xml,
                      headers=headers)
    assert r.status_code == 200, r.text

    # Testing, that user2 is not able to write to layer of user1
    authn_headers2 = get_authz_headers(username2)

    headers2 = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
        **authn_headers2,
    }

    client_util.reserve_username(username2, headers=authn_headers2)

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers2)
    assert r.status_code == 400, r.text

    # Testing, that user2 is not able to write user1's layer through general WFS endpoint
    general_rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/wfs?request=Transaction"
    r = requests.post(general_rest_url,
                      data=data_xml,
                      headers=headers2)
    assert r.status_code == 400, r.text

    # Test anonymous
    headers3 = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
    }

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers3)
    assert r.status_code == 400, r.text

    # Test fraud header
    headers4 = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
        settings.LAYMAN_GS_AUTHN_HTTP_HEADER_ATTRIBUTE: username,
    }

    r = requests.post(rest_url,
                      data=data_xml,
                      headers=headers4)
    assert r.status_code == 400, r.text

    client_util.delete_workspace_layer(username, layername1, headers=headers)


@pytest.mark.usefixtures('ensure_layman', 'liferay_mock')
@pytest.mark.parametrize('service_endpoint', ['ows', 'wms'])
def test_wms_ows_proxy(service_endpoint):
    username = 'test_wms_ows_proxy_user'
    layername = 'test_wms_ows_proxy_layer'

    authn_headers = get_authz_headers(username)

    client_util.ensure_reserved_username(username, headers=authn_headers)
    client_util.publish_workspace_layer(username, layername, headers=authn_headers)

    wms_url = geoserver_client.get_wms_url(username, service_endpoint)

    layer_info = client_util.get_workspace_layer(username, layername, headers=authn_headers)
    tn_bbox = get_square_bbox(layer_info['bounding_box'])

    from layman.layer.geoserver.wms import VERSION
    r = get_layer_thumbnail(wms_url, layername, tn_bbox, headers=authn_headers, wms_version=VERSION)
    r.raise_for_status()
    assert 'image' in r.headers['content-type']

    client_util.delete_workspace_layer(username, layername, headers=authn_headers)


@pytest.mark.timeout(60)
@pytest.mark.usefixtures('ensure_layman', 'liferay_mock')
@pytest.mark.parametrize('style_file', [
    None,
    'sample/style/ne_10m_admin_0_countries.qml',
])
def test_missing_attribute(style_file, ):
    username = 'testmissingattr'
    layername = 'inexisting_attribute_layer'
    layername2 = 'inexisting_attribute_layer2'

    authn_headers = get_authz_headers(username)
    headers = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
        **authn_headers,
    }

    client_util.ensure_reserved_username(username, headers=authn_headers)
    client_util.publish_workspace_layer(username,
                                        layername,
                                        file_paths=['tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson', ],
                                        style_file=style_file,
                                        headers=authn_headers,
                                        )
    client_util.publish_workspace_layer(username,
                                        layername2,
                                        file_paths=['tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson', ],
                                        style_file=style_file,
                                        headers=authn_headers,
                                        )

    wfs_t_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/wfs?request=Transaction"
    with app.app_context():
        style_type = layer_util.get_layer_info(username, layername, context={'keys': ['style_type'], })['style_type']

    def wfs_post(workspace, attr_names_list, data_xml):
        with app.app_context():
            wfs_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/{workspace}/wfs"
            old_db_attributes = {}
            old_wfs_properties = {}
            for layer, attr_names in attr_names_list:
                # test that all attr_names are not yet presented in DB table
                old_db_attributes[layer] = db.get_all_column_names(workspace, layer)
                for attr_name in attr_names:
                    assert attr_name not in old_db_attributes[layer], f"old_db_attributes={old_db_attributes[layer]}, attr_name={attr_name}"
                layer_schema = get_wfs_schema(
                    wfs_url, typename=f"{workspace}:{layer}", version=geoserver_wfs.VERSION, headers=authn_headers)
                old_wfs_properties[layer] = sorted(layer_schema['properties'].keys())
                if style_type == 'qml':
                    assert qgis_wms.get_layer_info(workspace, layer)
                    old_qgis_attributes = qgis_util.get_layer_attribute_names(workspace, layer)
                    assert all(attr_name not in old_qgis_attributes for attr_name in attr_names), (attr_names, old_qgis_attributes)

            r = requests.post(wfs_t_url,
                              data=data_xml,
                              headers=headers)
            assert r.status_code == 200, f"r.status_code={r.status_code}\n{r.text}"

            new_db_attributes = {}
            new_wfs_properties = {}
            for layer, attr_names in attr_names_list:
                # test that exactly all attr_names were created in DB table
                new_db_attributes[layer] = db.get_all_column_names(workspace, layer)
                for attr_name in attr_names:
                    assert attr_name in new_db_attributes[layer], f"new_db_attributes={new_db_attributes[layer]}, attr_name={attr_name}"
                assert set(attr_names).union(set(old_db_attributes[layer])) == set(new_db_attributes[layer])

                # test that exactly all attr_names were distinguished also in WFS feature type
                layer_schema = get_wfs_schema(
                    wfs_url, typename=f"{workspace}:{layer}", version=geoserver_wfs.VERSION, headers=authn_headers)
                new_wfs_properties[layer] = sorted(layer_schema['properties'].keys())
                for attr_name in attr_names:
                    assert attr_name in new_wfs_properties[layer], f"new_wfs_properties={new_wfs_properties[layer]}, attr_name={attr_name}"
                assert set(attr_names).union(set(old_wfs_properties[layer])) == set(new_wfs_properties[layer]),\
                    set(new_wfs_properties[layer]).difference(set(attr_names).union(set(old_wfs_properties[layer])))
                if style_type == 'qml':
                    assert qgis_wms.get_layer_info(workspace, layer)
                    new_qgis_attributes = qgis_util.get_layer_attribute_names(workspace, layer)
                    assert all(attr_name in new_qgis_attributes for attr_name in attr_names), (attr_names, new_qgis_attributes)
                else:
                    assert not qgis_wms.get_layer_info(workspace, layer)

    attr_names = ['inexisting_attribute_attr', 'inexisting_attribute_attr1a']
    data_xml = data_wfs.get_wfs20_insert_points_new_attr(username, layername, attr_names)
    wfs_post(username, [(layername, attr_names)], data_xml)

    attr_names2 = ['inexisting_attribute_attr2']
    data_xml = data_wfs.get_wfs20_update_points_new_attr(username, layername, attr_names2)
    wfs_post(username, [(layername, attr_names2)], data_xml)

    attr_names3 = ['inexisting_attribute_attr3']
    data_xml = data_wfs.get_wfs20_update_points_new_attr(username, layername, attr_names3, with_attr_namespace=True)
    wfs_post(username, [(layername, attr_names3)], data_xml)

    attr_names4 = ['inexisting_attribute_attr4']
    data_xml = data_wfs.get_wfs20_update_points_new_attr(username, layername, attr_names4, with_filter=True)
    wfs_post(username, [(layername, attr_names4)], data_xml)

    attr_names5 = ['inexisting_attribute_attr5']
    data_xml = data_wfs.get_wfs20_replace_points_new_attr(username, layername, attr_names5)
    wfs_post(username, [(layername, attr_names5)], data_xml)

    attr_names_i1 = ['inexisting_attribute_attr_complex_i1']
    attr_names_i2 = ['inexisting_attribute_attr_complex_i2']
    attr_names_u = ['inexisting_attribute_attr_complex_u']
    attr_names_r = ['inexisting_attribute_attr_complex_r']
    attr_names_complex = [(layername, attr_names_i1 + attr_names_r), (layername2, attr_names_i2 + attr_names_u)]
    data_xml = data_wfs.get_wfs20_complex_new_attr(workspace=username,
                                                   layername1=layername,
                                                   layername2=layername2,
                                                   attr_names_insert1=attr_names_i1,
                                                   attr_names_insert2=attr_names_i2,
                                                   attr_names_update=attr_names_u,
                                                   attr_names_replace=attr_names_r
                                                   )
    wfs_post(username, attr_names_complex, data_xml)

    attr_names6 = ['inexisting_attribute_attr6']
    data_xml = data_wfs.get_wfs10_insert_points_new_attr(username, layername, attr_names6)
    wfs_post(username, [(layername, attr_names6)], data_xml)

    attr_names7 = ['inexisting_attribute_attr7']
    data_xml = data_wfs.get_wfs11_insert_points_new_attr(username, layername, attr_names7)
    wfs_post(username, [(layername, attr_names7)], data_xml)

    attr_names8 = ['inexisting_attribute_attr8']
    data_xml = data_wfs.get_wfs10_update_points_new(username, layername, attr_names8, with_attr_namespace=True)
    wfs_post(username, [(layername, attr_names8)], data_xml)

    attr_names9 = ['inexisting_attribute_attr9']
    data_xml = data_wfs.get_wfs10_update_points_new(username, layername, attr_names9, with_filter=True)
    wfs_post(username, [(layername, attr_names9)], data_xml)

    attr_names10 = ['inexisting_attribute_attr10']
    data_xml = data_wfs.get_wfs11_insert_polygon_new_attr(username, layername, attr_names10)
    wfs_post(username, [(layername, attr_names10)], data_xml)

    time.sleep(5)

    client_util.delete_workspace_layer(username, layername, headers=headers)
    client_util.delete_workspace_layer(username, layername2, headers=headers)


@pytest.mark.usefixtures('ensure_layman', 'liferay_mock')
def test_missing_attribute_authz():
    username = 'testmissingattr_authz'
    layername1 = 'testmissingattr_authz_layer'
    username2 = 'testmissingattr_authz2'

    authn_headers1 = get_authz_headers(username)
    authn_headers2 = get_authz_headers(username2)
    headers1 = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
        **authn_headers1,
    }
    headers2 = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
        **authn_headers2,
    }

    def do_test(wfs_query, attribute_names):
        # Test, that unauthorized user will not cause new attribute
        with app.app_context():
            old_db_attributes = db.get_all_column_names(username, layername1)
        for attr_name in attribute_names:
            assert attr_name not in old_db_attributes, f"old_db_attributes={old_db_attributes}, attr_name={attr_name}"
        r = requests.post(rest_url,
                          data=wfs_query,
                          headers=headers2)
        assert r.status_code == 400, r.text
        with app.app_context():
            new_db_attributes = db.get_all_column_names(username, layername1)
        for attr_name in attribute_names:
            assert attr_name not in new_db_attributes, f"new_db_attributes={new_db_attributes}, attr_name={attr_name}"

        # Test, that authorized user will cause new attribute
        r = requests.post(rest_url,
                          data=wfs_query,
                          headers=headers1)
        assert r.status_code == 200, r.text
        with app.app_context():
            new_db_attributes = db.get_all_column_names(username, layername1)
        for attr_name in attribute_names:
            assert attr_name in new_db_attributes, f"new_db_attributes={new_db_attributes}, attr_name={attr_name}"

    client_util.reserve_username(username, headers=authn_headers1)
    client_util.publish_workspace_layer(username,
                                        layername1,
                                        file_paths=['tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson', ],
                                        headers=authn_headers1)

    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/{username}/wfs?request=Transaction"

    # Testing, that user2 is not able to write to layer of user1
    client_util.reserve_username(username2, headers=authn_headers2)

    # INSERT
    attr_names = ['inexisting_attribute_auth1', 'inexisting_attribute_auth2']
    data_xml = data_wfs.get_wfs20_insert_points_new_attr(username, layername1, attr_names)
    do_test(data_xml, attr_names)

    # UPDATE
    attr_names = ['inexisting_attribute_auth3', 'inexisting_attribute_auth4']
    data_xml = data_wfs.get_wfs20_update_points_new_attr(username, layername1, attr_names)
    do_test(data_xml, attr_names)

    time.sleep(5)

    client_util.delete_workspace_layer(username, layername1, headers=headers1)


def assert_all_sources_bbox(workspace, layer, expected_bbox):
    with app.app_context():
        bbox = tuple(layman_util.get_publication_info(workspace, client_util.LAYER_TYPE, layer,
                                                      context={'key': ['bounding_box']})['bounding_box'])
    test_util.assert_same_bboxes(expected_bbox, bbox, 0)
    test_util.assert_wfs_bbox(workspace, layer, expected_bbox)
    test_util.assert_wms_bbox(workspace, layer, expected_bbox)

    with app.app_context():
        expected_bbox_4326 = bbox_util.transform(expected_bbox, 3857, 4326, )
    md_comparison = client_util.get_workspace_layer_metadata_comparison(workspace, layer)
    csw_prefix = settings.CSW_PROXY_URL
    csw_src_key = client_util.get_source_key_from_metadata_comparison(md_comparison, csw_prefix)
    assert csw_src_key is not None
    prop_key = 'extent'
    md_props = md_comparison['metadata_properties']
    assert md_props[prop_key]['equal'] is True
    assert md_props[prop_key]['equal_or_null'] is True
    csw_bbox_4326 = tuple(md_props[prop_key]['values'][csw_src_key])
    test_util.assert_same_bboxes(expected_bbox_4326, csw_bbox_4326, 0.001)


@pytest.mark.parametrize('style_file, thumbnail_style_postfix', [
    (None, '_sld'),
    ('sample/style/small_layer.qml', '_qml'),
])
@pytest.mark.usefixtures('ensure_layman')
def test_wfs_bbox(style_file, thumbnail_style_postfix):
    workspace = 'test_wfs_bbox_workspace'
    layer = 'test_wfs_bbox_layer'

    client_util.publish_workspace_layer(workspace, layer, style_file=style_file, )

    assert_all_sources_bbox(workspace, layer, SMALL_LAYER_BBOX)

    rest_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/{workspace}/wfs?request=Transaction"
    headers = {
        'Accept': 'text/xml',
        'Content-type': 'text/xml',
    }

    expected_bbox = (1571000.0, 6268800.0, 1572590.8542062, 6269876.33561699)
    method_bbox_thumbnail_tuples = [
        (data_wfs.get_wfs20_insert_points, expected_bbox, '_bigger'),
        (data_wfs.get_wfs20_delete_point, SMALL_LAYER_BBOX, ''),
    ]

    for wfs_method, exp_bbox, thumbnail_bbox_postfix in method_bbox_thumbnail_tuples:
        data_xml = wfs_method(workspace, layer, )

        r = requests.post(rest_url,
                          data=data_xml,
                          headers=headers)
        assert r.status_code == 200, r.text

        # until there is way to check end of asynchronous task after WFS-T
        time.sleep(5)

        assert_all_sources_bbox(workspace, layer, exp_bbox)

        expected_thumbnail_path = f'/code/sample/style/{layer}{thumbnail_style_postfix}{thumbnail_bbox_postfix}.png'
        with app.app_context():
            thumbnail_path = thumbnail.get_layer_thumbnail_path(workspace, layer)
        diffs = test_util.compare_images(expected_thumbnail_path, thumbnail_path)
        assert diffs < 100, expected_thumbnail_path

    client_util.delete_workspace_layer(workspace, layer, )
