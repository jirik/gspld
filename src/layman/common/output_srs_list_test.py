import math
from test import process, process_client, geoserver_client, util
import pytest

from layman import settings, app
from layman.layer.qgis import util as qgis_util, wms as qgis_wms


LAYERS_TO_DELETE_AFTER_TEST = []


OUTPUT_SRS_LIST = [4326, 3857, 32633, 32634, 3059, 5514]


def test_default_srs_list():
    assert settings.LAYMAN_OUTPUT_SRS_LIST == [4326, 3857, 5514]


@pytest.fixture(scope="module")
def delete_layer_after_test():
    def register_layer_to_delete(workspace, layername):
        LAYERS_TO_DELETE_AFTER_TEST.append((workspace, layername))
    yield register_layer_to_delete
    for workspace, layername in LAYERS_TO_DELETE_AFTER_TEST:
        process_client.delete_workspace_layer(workspace, layername)


@pytest.fixture(scope="module")
def ensure_layer(delete_layer_after_test):
    def ensure_layer_internal(workspace, layername, file_paths=None, style_file=None):
        if (workspace, layername) not in LAYERS_TO_DELETE_AFTER_TEST:
            process_client.publish_workspace_layer(workspace, layername, file_paths=file_paths, style_file=style_file)
            delete_layer_after_test(workspace, layername)
        else:
            process_client.patch_workspace_layer(workspace, layername, file_paths=file_paths, style_file=style_file)
    yield ensure_layer_internal


@pytest.fixture(scope="module")
def ensure_layers(delete_layer_after_test):
    def ensure_layers_internal(layers):
        to_publish = [layer for layer in layers if (layer['username'], layer['name']) not in LAYERS_TO_DELETE_AFTER_TEST]
        to_patch = [layer for layer in layers if (layer['username'], layer['name']) in LAYERS_TO_DELETE_AFTER_TEST]
        process_client.publish_publications(layers)
        for layer in to_publish:
            delete_layer_after_test(layer['username'], layer['name'])
        else:
            for layer in to_patch:
                process_client.patch_workspace_layer(**layer)
    yield ensure_layers_internal


def test_custom_srs_list(ensure_layers):
    workspace = 'test_custom_srs_list_workspace'
    layer_sld1 = 'test_custom_srs_list_sld_layer1'
    layer_sld2 = 'test_custom_srs_list_sld_layer2'
    layer_qgis1 = 'test_custom_srs_list_qgis_layer1'
    layer_qgis2 = 'test_custom_srs_list_qgis_layer2'
    source_style_file_path = 'sample/style/small_layer.qml'
    assert settings.LAYMAN_OUTPUT_SRS_LIST != OUTPUT_SRS_LIST

    process.ensure_layman_function(process.LAYMAN_DEFAULT_SETTINGS)
    ensure_layers([{'username': workspace,
                    'publication_type': process_client.LAYER_TYPE,
                    'name': layer_sld1,
                    },
                   {'username': workspace,
                    'publication_type': process_client.LAYER_TYPE,
                    'name': layer_qgis1,
                    'style_file': source_style_file_path,
                    },
                   ])

    with app.app_context():
        assert_gs_wms_output_srs_list(workspace, layer_sld1, settings.LAYMAN_OUTPUT_SRS_LIST)
        assert_wfs_output_srs_list(workspace, layer_sld1, settings.LAYMAN_OUTPUT_SRS_LIST)
        assert not qgis_wms.get_layer_info(workspace, layer_sld1)

        assert_gs_wms_output_srs_list(workspace, layer_qgis1, settings.LAYMAN_OUTPUT_SRS_LIST)
        assert_wfs_output_srs_list(workspace, layer_qgis1, settings.LAYMAN_OUTPUT_SRS_LIST)
        assert_qgis_output_srs_list(workspace, layer_qgis1, settings.LAYMAN_OUTPUT_SRS_LIST)
        assert_qgis_wms_output_srs_list(workspace, layer_qgis1, settings.LAYMAN_OUTPUT_SRS_LIST)

    process.ensure_layman_function({
        'LAYMAN_OUTPUT_SRS_LIST': ','.join([str(code) for code in OUTPUT_SRS_LIST])
    })
    ensure_layers([{'username': workspace,
                    'publication_type': process_client.LAYER_TYPE,
                    'name': layer_sld2,
                    },
                   {'username': workspace,
                    'publication_type': process_client.LAYER_TYPE,
                    'name': layer_qgis2,
                    'style_file': source_style_file_path,
                    },
                   ])

    with app.app_context():
        for layer in [layer_sld1, layer_sld2, ]:
            assert_gs_wms_output_srs_list(workspace, layer, OUTPUT_SRS_LIST)
            assert_wfs_output_srs_list(workspace, layer, OUTPUT_SRS_LIST)
            assert not qgis_wms.get_layer_info(workspace, layer)
        for layer in [layer_qgis1, layer_qgis2, ]:
            assert_gs_wms_output_srs_list(workspace, layer, OUTPUT_SRS_LIST)
            assert_wfs_output_srs_list(workspace, layer, OUTPUT_SRS_LIST)
            assert_qgis_output_srs_list(workspace, layer, OUTPUT_SRS_LIST)
            assert_qgis_wms_output_srs_list(workspace, layer, OUTPUT_SRS_LIST)


def assert_gs_wms_output_srs_list(workspace, layername, expected_output_srs_list):
    wms = geoserver_client.get_wms_capabilities(workspace)
    assert layername in wms.contents
    wms_layer = wms.contents[layername]
    for expected_output_srs in expected_output_srs_list:
        assert f"EPSG:{expected_output_srs}" in wms_layer.crsOptions


def assert_qgis_wms_output_srs_list(workspace, layer, expected_output_srs_list):
    wms = qgis_wms.get_wms_capabilities(workspace, layer)
    assert layer in wms.contents
    wms_layer = wms.contents[layer]
    for expected_output_srs in expected_output_srs_list:
        assert f"EPSG:{expected_output_srs}" in wms_layer.crsOptions


def assert_wfs_output_srs_list(workspace, layername, expected_output_srs_list):
    wfs = geoserver_client.get_wfs_capabilities(workspace)
    full_layername = f"{workspace}:{layername}"
    assert full_layername in wfs.contents
    wfs_layer = wfs.contents[full_layername]
    crs_names = [str(crs) for crs in wfs_layer.crsOptions]
    for expected_output_srs in expected_output_srs_list:
        assert f"urn:ogc:def:crs:EPSG::{expected_output_srs}" in crs_names


def assert_qgis_output_srs_list(workspace, layer, expected_srs_list):
    with app.app_context():
        assert qgis_util.get_layer_wms_crs_list_values(workspace, layer) == set(expected_srs_list)


# expected coordinates manually copied from QGIS 3.16.2 in given EPSG
# point_id 1: northernmost vertex of fountain at Moravske namesti, Brno
@pytest.mark.parametrize('point_id, epsg_code, exp_coordinates, precision', [
    (1, 3857, (1848649.486, 6308703.297), 0.2),
    # ~5 meters! By default, GeoServer limits WFS output to 4 decimal places, about 10 m accuracy
    (1, 4326, (16.60669976, 49.19904767), 0.00005),
    (1, 32633, (617046.8503, 5450825.7990), 0.1),
    (1, 32634, (179991.0748, 5458879.0878), 0.1),
    (1, 5514, (-598208.8093, -1160307.4484), 0.1),
])
def test_spatial_precision(ensure_layer, point_id, epsg_code, exp_coordinates, precision, ):
    process.ensure_layman_function({
        'LAYMAN_OUTPUT_SRS_LIST': ','.join([str(code) for code in OUTPUT_SRS_LIST])
    })
    workspace = 'test_coordinate_precision_workspace'
    layername = 'test_coordinate_precision_layer'

    ensure_layer(workspace, layername, file_paths=['sample/layman.layer/sample_point_cz.geojson'], )

    feature_collection = geoserver_client.get_features(workspace, layername, epsg_code=epsg_code)
    feature = next(f for f in feature_collection['features'] if f['properties']['point_id'] == point_id)
    for idx, coordinate in enumerate(feature['geometry']['coordinates']):
        assert abs(coordinate - exp_coordinates[idx]) <= precision, f"EPSG:{epsg_code}: expected coordinates={exp_coordinates}, found coordinates={feature['geometry']['coordinates']}"


@pytest.mark.parametrize('epsg_code, extent, img_size, style_type, wms_version, diff_line_width, suffix', [
    (3857, (1848629.922, 6308682.319, 1848674.659, 6308704.687), (601, 301), 'sld', '1.3.0', 2, ''),
    (3857, (1848629.922, 6308682.319, 1848674.659, 6308704.687), (601, 301), 'qml', '1.3.0', 2, ''),
    (4326, (49.198905759, 16.606580653, 49.199074214, 16.606874005), (560, 321), 'sld', '1.3.0', 2, ''),
    (4326, (49.198905759, 16.606580653, 49.199074214, 16.606874005), (560, 321), 'qml', '1.3.0', 2, ''),
    (4326, (16.606580653, 49.198905759, 16.606874005, 49.199074214), (560, 321), 'sld', '1.1.1', 2, ''),
    (4326, (16.606580653, 49.198905759, 16.606874005, 49.199074214), (560, 321), 'qml', '1.1.1', 2, ''),
    (5514, (-598222.071, -1160322.246, -598192.491, -1160305.260), (559, 321), 'sld', '1.3.0', 2, ''),
    # (5514, (-598222.071, -1160322.246, -598192.491, -1160305.260), (559, 321), 'qml', '1.3.0', 2, ''),
    (5514, (-598236.981, -1160331.352, -598182.368, -1160295.230), (381, 252), 'sld', '1.3.0', 2, '_low'),
    (5514, (-598236.981, -1160331.352, -598182.368, -1160295.230), (381, 252), 'qml', '1.3.0', 4, '_low'),
    (32633, (617036.812, 5450809.904, 617060.659, 5450828.394), (414, 321), 'sld', '1.3.0', 2, ''),
    (32633, (617036.812, 5450809.904, 617060.659, 5450828.394), (414, 321), 'qml', '1.3.0', 2, ''),
    (32634, (179980.621, 5458862.472, 180005.430, 5458881.708), (415, 321), 'sld', '1.3.0', 2, ''),
    (32634, (179980.621, 5458862.472, 180005.430, 5458881.708), (415, 321), 'qml', '1.3.0', 2, ''),
])
def test_spatial_precision_wms(ensure_layer, epsg_code, extent, img_size, style_type, wms_version, diff_line_width, suffix):
    process.ensure_layman_function({
        'LAYMAN_OUTPUT_SRS_LIST': ','.join([str(code) for code in OUTPUT_SRS_LIST])
    })
    workspace = 'test_spatial_precision_wms_workspace'
    layer = f'test_spatial_precision_wms_layer_{style_type}'

    ensure_layer(workspace, layer, file_paths=['sample/layman.layer/sample_point_cz.geojson'], style_file=f'sample/layman.layer/sample_point_cz.{style_type}')

    expected_file = f'sample/layman.layer/sample_point_cz_{epsg_code}{suffix}.png'
    obtained_file = f'tmp/artifacts/test_spatial_precision_wms/sample_point_cz_{style_type}_{epsg_code}{suffix}.png'
    crs_name = {
        '1.1.1': 'SRS',
        '1.3.0': 'CRS',
    }[wms_version]

    url = f'http://{settings.LAYMAN_SERVER_NAME}/geoserver/{workspace}_wms/wms?SERVICE=WMS&VERSION={wms_version}&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&STYLES&LAYERS={workspace}_wms%3A{layer}&FORMAT_OPTIONS=antialias%3Afull&{crs_name}=EPSG%3A{epsg_code}&WIDTH={img_size[0]}&HEIGHT={img_size[1]}&BBOX={"%2C".join((str(c) for c in extent))}'

    circle_diameter = 30
    circle_perimeter = circle_diameter * math.pi
    num_circles = 5
    pixel_diff_limit = circle_perimeter * num_circles * diff_line_width

    util.assert_same_images(url, obtained_file, expected_file, pixel_diff_limit)
