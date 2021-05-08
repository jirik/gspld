from urllib.parse import urljoin
from test import process_client, assert_util
import requests
import pytest

from geoserver import GS_REST, GS_AUTH
from layman import settings


headers_sld = {
    'Accept': 'application/vnd.ogc.sld+xml',
    'Content-type': 'application/xml',
}


@pytest.mark.usefixtures('ensure_layman')
def test_sld_style_in_wms_workspace():
    workspace = 'test_sld_style_file_workspace'
    layer = 'test_sld_style_file_layer'
    geojson_file = ['/code/tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson']
    style_file = 'sample/style/generic-blue_sld.xml'

    process_client.publish_workspace_layer(workspace,
                                           layer,
                                           file_paths=geojson_file,
                                           style_file=style_file)

    url = urljoin(GS_REST, f'workspaces/{workspace}_wms/styles/{layer}')

    r = requests.get(url,
                     auth=GS_AUTH,
                     headers=headers_sld,
                     timeout=5,
                     )
    r.raise_for_status()
    process_client.delete_workspace_layer(workspace,
                                          layer)


@pytest.mark.usefixtures('ensure_layman')
def test_sld_style_applied_in_wms():
    workspace = 'test_sld_style_wms_workspace'
    layer = 'test_sld_style_wms_layer'
    geojson_file = ['/code/tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson']
    style_file = 'sample/style/generic-blue_sld.xml'
    expected_file = 'sample/style/countries_wms_blue.png'
    obtained_file = 'tmp/artifacts/test_sld_style_applied_in_wms.png'

    process_client.publish_workspace_layer(workspace,
                                           layer,
                                           file_paths=geojson_file,
                                           style_file=style_file)

    url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/{workspace}_wms/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&FORMAT=image/png&TRANSPARENT=true&STYLES=&LAYERS={workspace}:{layer}&SRS=EPSG:3857&WIDTH=768&HEIGHT=752&BBOX=-30022616.05686392,-30569903.32873383,30022616.05686392,28224386.44929134"

    assert_util.assert_same_images(url, obtained_file, expected_file, 2000)

    process_client.delete_workspace_layer(workspace,
                                          layer)
