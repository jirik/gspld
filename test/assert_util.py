import os
import pathlib
import requests

from layman import app, util as layman_util, settings
from layman.common import bbox as bbox_util
from layman.layer.geoserver import wfs, wms
from .process_client import LAYER_TYPE, get_workspace_layer_metadata_comparison, get_source_key_from_metadata_comparison
from .util import compare_images


def assert_same_images(img_url, tmp_file_path, expected_file_path, diff_threshold):
    r = requests.get(img_url,
                     timeout=5,
                     )
    r.raise_for_status()
    pathlib.Path(os.path.dirname(tmp_file_path)).mkdir(parents=True, exist_ok=True)
    with open(tmp_file_path, 'wb') as f:
        for chunk in r:
            f.write(chunk)

    diffs = compare_images(expected_file_path, tmp_file_path)

    assert diffs < diff_threshold, f"{diffs} >= {diff_threshold}"

    os.remove(tmp_file_path)


def assert_same_bboxes(bbox1, bbox2, precision):
    assert len(bbox1) == 4, (bbox1, len(bbox1))
    assert len(bbox2) == 4, (bbox2, len(bbox2))
    for i in range(0, 3):
        assert abs(bbox2[i] - bbox1[i]) <= precision, (bbox1, bbox2, precision, i)


def assert_wfs_bbox(workspace, layer, expected_bbox):
    wfs_layer = f"{workspace}:{layer}"
    with app.app_context():
        wfs_get_capabilities = wfs.get_wfs_proxy(workspace)
    wfs_bbox_4326 = wfs_get_capabilities.contents[wfs_layer].boundingBoxWGS84
    with app.app_context():
        wfs_bbox_3857 = bbox_util.transform(wfs_bbox_4326, 4326, 3857, )
    assert_same_bboxes(expected_bbox, wfs_bbox_3857, 0.00001)


def assert_wms_bbox(workspace, layer, expected_bbox):
    with app.app_context():
        wms_get_capabilities = wms.get_wms_proxy(workspace)
    wms_layer = wms_get_capabilities.contents[layer]
    bbox_3857 = next(bbox[:4] for bbox in wms_layer.crs_list if bbox[4] == 'EPSG:3857')
    assert_same_bboxes(expected_bbox, bbox_3857, 0.00001)

    with app.app_context():
        expected_bbox_4326 = bbox_util.transform(expected_bbox, 3857, 4326, )
    wgs84_bboxes = [bbox[:4] for bbox in wms_layer.crs_list if bbox[4] in ['EPSG:4326', 'CRS:84']]
    wgs84_bboxes.append(wms_layer.boundingBoxWGS84)
    for wgs84_bbox in wgs84_bboxes:
        assert_same_bboxes(expected_bbox_4326, wgs84_bbox, 0.00001)


def assert_all_sources_bbox(workspace, layer, expected_bbox):
    with app.app_context():
        bbox = tuple(layman_util.get_publication_info(workspace, LAYER_TYPE, layer,
                                                      context={'key': ['bounding_box']})['bounding_box'])
    assert_same_bboxes(expected_bbox, bbox, 0)
    assert_wfs_bbox(workspace, layer, expected_bbox)
    assert_wms_bbox(workspace, layer, expected_bbox)

    with app.app_context():
        expected_bbox_4326 = bbox_util.transform(expected_bbox, 3857, 4326, )
    md_comparison = get_workspace_layer_metadata_comparison(workspace, layer)
    csw_prefix = settings.CSW_PROXY_URL
    csw_src_key = get_source_key_from_metadata_comparison(md_comparison, csw_prefix)
    assert csw_src_key is not None
    prop_key = 'extent'
    md_props = md_comparison['metadata_properties']
    assert md_props[prop_key]['equal'] is True, md_props[prop_key]
    assert md_props[prop_key]['equal_or_null'] is True, md_props[prop_key]
    csw_bbox_4326 = tuple(md_props[prop_key]['values'][csw_src_key])
    assert_same_bboxes(expected_bbox_4326, csw_bbox_4326, 0.001)
