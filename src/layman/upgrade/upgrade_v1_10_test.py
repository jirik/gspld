from datetime import date
import pathlib
import shutil
import os
from collections import namedtuple
from test import process_client, util, assert_util
from test.util import url_for
import pytest

from db import util as db_util
from geoserver import util as gs_util
from layman import app, settings
from layman.http import LaymanError
from layman.common import prime_db_schema
from layman.layer import geoserver as gs_layer, util as layer_util, db, NO_STYLE_DEF
from layman.layer.prime_db_schema import table as prime_db_schema_table
from layman.layer.geoserver import wms
from layman.layer.filesystem import util as layer_fs_util, input_style
from layman.map.filesystem import input_file, thumbnail
from layman.map import util as map_util
from layman.common.db import launder_attribute_name
from layman.common.micka import util as micka_util
from layman.common.filesystem import uuid as uuid_common
from layman.uuid import generate_uuid
from . import upgrade_v1_10
DB_SCHEMA = settings.LAYMAN_PRIME_SCHEMA


@pytest.fixture()
def publications_constraint():
    drop_constraint = f'alter table {DB_SCHEMA}.publications drop constraint if exists con_style_type'
    with app.app_context():
        db_util.run_statement(drop_constraint)
    yield
    add_constraint = f"""DO $$ BEGIN
        alter table {DB_SCHEMA}.publications add constraint con_style_type
    check (type = 'layman.map' or style_type is not null);
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;"""
    with app.app_context():
        db_util.run_statement(add_constraint)


@pytest.mark.usefixtures('ensure_layman')
def test_check_usernames_wms_suffix():
    username = 'test_check_usernames_wms_suffix'
    username_wms = 'test_check_usernames_wms_suffix' + settings.LAYMAN_GS_WMS_WORKSPACE_POSTFIX

    with app.app_context():
        prime_db_schema.ensure_workspace(username)
        upgrade_v1_10.check_workspace_names()

        prime_db_schema.ensure_workspace(username_wms)
        with pytest.raises(LaymanError) as exc_info:
            upgrade_v1_10.check_workspace_names()
        assert exc_info.value.data['workspace'] == username_wms
        prime_db_schema.delete_workspace(username)
        prime_db_schema.delete_workspace(username_wms)


@pytest.mark.usefixtures('ensure_layman')
def test_check_usernames_workspaces():
    username = 'workspaces'

    with app.app_context():
        prime_db_schema.ensure_workspace(username)
        with pytest.raises(LaymanError) as exc_info:
            upgrade_v1_10.check_workspace_names()
        assert exc_info.value.data['workspace'] == username
        prime_db_schema.delete_workspace(username)


@pytest.fixture()
def ensure_layer():
    def ensure_layer_internal(workspace, layer):
        access_rights = {'read': [settings.RIGHTS_EVERYONE_ROLE], 'write': [settings.RIGHTS_EVERYONE_ROLE], }
        style_file = 'sample/style/generic-blue_sld.xml'
        with app.app_context():
            uuid_str = generate_uuid()
            prime_db_schema_table.post_layer(workspace,
                                             layer,
                                             access_rights,
                                             layer,
                                             uuid_str,
                                             None,
                                             NO_STYLE_DEF,
                                             )
            file_path = '/code/tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson'
            uuid_common.assign_publication_uuid('layman.layer', workspace, layer, uuid_str=uuid_str)
            db.ensure_workspace(workspace)
            db.import_layer_vector_file(workspace, layer, file_path, None)
            created = gs_util.ensure_workspace(workspace, settings.LAYMAN_GS_AUTH)
            if created:
                gs_util.create_db_store(workspace, settings.LAYMAN_GS_AUTH, db_schema=workspace, pg_conn=settings.PG_CONN)
            gs_layer.publish_layer_from_db(workspace, layer, layer, layer, None, workspace)
            sld_file_path = 'sample/style/generic-blue_sld.xml'
            with open(sld_file_path, 'rb') as sld_file:
                gs_util.post_workspace_sld_style(workspace, layer, sld_file, launder_attribute_name)
            md_path = '/code/src/layman/upgrade/upgrade_v1_10_test_layer_metadata.xml'
            with open(md_path, 'r') as template_file:
                md_template = template_file.read()
            record = md_template.format(uuid=uuid_str,
                                        md_date_stamp=date.today().strftime('%Y-%m-%d'),
                                        publication_date=date.today().strftime('%Y-%m-%d'),
                                        workspace=workspace,
                                        layer=layer,
                                        )
            micka_util.soap_insert_record(record, is_public=True)

            input_sld_dir = os.path.join(layer_fs_util.get_layer_dir(workspace, layer),
                                         'input_sld')
            pathlib.Path(input_sld_dir).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(style_file, os.path.join(input_sld_dir, layer + '.xml'))

    yield ensure_layer_internal


@pytest.mark.usefixtures('ensure_layman')
def test_migrate_layers_to_wms_workspace(ensure_layer):
    workspace = 'test_migrate_layers_to_wms_workspace_workspace'
    layer = 'test_migrate_layers_to_wms_workspace_layer'
    expected_file = 'sample/style/countries_wms_blue.png'
    ensure_layer(workspace, layer)

    layer_info = process_client.get_workspace_layer(workspace, layer)

    assert layer_info['wms']['status'] == 'NOT_AVAILABLE'
    assert layer_info['wfs']['url'] == f'http://localhost:8000/geoserver/{workspace}/wfs'
    assert layer_info['db_table']['name'] == layer

    all_workspaces = gs_util.get_all_workspaces(settings.LAYMAN_GS_AUTH)
    assert workspace in all_workspaces
    wms_workspace = wms.get_geoserver_workspace(workspace)
    assert wms_workspace not in all_workspaces
    sld_wfs_r = gs_util.get_workspace_style_response(workspace, layer, auth=settings.LAYMAN_GS_AUTH)
    assert sld_wfs_r.status_code == 200

    old_wms_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/" \
                  f"{workspace}/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&FORMAT=image/png&TRANSPARENT=true&STYLES=&" \
                  f"LAYERS={workspace}:{layer}&SRS=EPSG:3857&WIDTH=768&HEIGHT=752&" \
                  f"BBOX=-30022616.05686392,-30569903.32873383,30022616.05686392,28224386.44929134"

    obtained_file = 'tmp/artifacts/test_migrate_layers_to_wms_workspace_before_migration.png'
    assert_util.assert_same_images(old_wms_url, obtained_file, expected_file, 2000)

    with app.app_context():
        upgrade_v1_10.migrate_layers_to_wms_workspace(workspace)

    layer_info = process_client.get_workspace_layer(workspace, layer)
    assert layer_info['wms']['url'] == f'http://localhost:8000/geoserver/{wms_workspace}/ows'
    assert layer_info['wfs']['url'] == f'http://localhost:8000/geoserver/{workspace}/wfs'
    with app.app_context():
        assert layer_info['style']['url'] == url_for('rest_workspace_layer_style.get', workspace=workspace, layername=layer,
                                                     internal=False)

    all_workspaces = gs_util.get_all_workspaces(settings.LAYMAN_GS_AUTH)
    assert workspace in all_workspaces
    assert wms_workspace in all_workspaces
    sld_wfs_r = gs_util.get_workspace_style_response(workspace, layer, auth=settings.LAYMAN_GS_AUTH)
    assert sld_wfs_r.status_code == 404
    sld_wms_r = gs_util.get_workspace_style_response(wms_workspace, layer, auth=settings.LAYMAN_GS_AUTH)
    assert sld_wms_r.status_code == 200

    sld_stream = process_client.get_workspace_layer_style(workspace, layer)
    assert sld_stream

    new_wms_url = f"http://{settings.LAYMAN_SERVER_NAME}/geoserver/" \
                  f"{wms_workspace}/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&FORMAT=image/png&TRANSPARENT=true&STYLES=&" \
                  f"LAYERS={wms_workspace}:{layer}&SRS=EPSG:3857&WIDTH=768&HEIGHT=752&" \
                  f"BBOX=-30022616.05686392,-30569903.32873383,30022616.05686392,28224386.44929134"
    obtained_file2 = 'tmp/artifacts/test_migrate_layers_to_wms_workspace_after_migration.png'
    assert_util.assert_same_images(new_wms_url, obtained_file2, expected_file, 2000)

    process_client.delete_workspace_layer(workspace, layer)


@pytest.fixture()
def ensure_map():

    def ensure_map_internal(workspace, map, layer_workspace, layer):
        geojson_files = ['/code/tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson']
        style_file = 'sample/style/generic-blue_sld.xml'
        source_map_file_path = '/code/src/layman/upgrade/upgrade_v1_10_test_map.json'
        process_client.publish_workspace_layer(layer_workspace,
                                               layer,
                                               file_paths=geojson_files,
                                               style_file=style_file)
        process_client.publish_workspace_map(workspace,
                                             map,
                                             )

        with app.app_context():
            input_file.ensure_map_input_file_dir(workspace, map)
            map_file_path = input_file.get_map_file(workspace, map)
            shutil.copyfile(source_map_file_path, map_file_path)
            thumbnail.generate_map_thumbnail(workspace, map, '')

    yield ensure_map_internal


@pytest.mark.usefixtures('ensure_layman')
def test_migrate_maps_on_wms_workspace(ensure_map):
    layer_workspace = 'test_migrate_maps_on_wms_workspace_layer_workspace'
    layer = 'test_migrate_maps_on_wms_workspace_layer'
    workspace = 'test_migrate_maps_on_wms_workspace_workspace'
    map = 'test_migrate_maps_on_wms_workspace_map'
    expected_file = 'sample/style/test_sld_style_applied_in_map_thumbnail_map.png'

    ensure_map(workspace, map, layer_workspace, layer)

    with app.app_context():
        map_json = input_file.get_map_json(workspace, map)
        assert map_json['layers'][0]['url'] == 'http://localhost:8000/geoserver/test_migrate_maps_on_wms_workspace_layer_workspace/ows',\
            map_json
        thumbnail_path = thumbnail.get_map_thumbnail_path(workspace, map)
    diffs_before = util.compare_images(expected_file, thumbnail_path)
    shutil.copyfile(thumbnail_path, '/code/tmp/artifacts/upgrade_v1_10_map_thumbnail_before.png')
    assert 28000 < diffs_before < 35000

    with app.app_context():
        upgrade_v1_10.migrate_maps_on_wms_workspace()

    with app.app_context():
        map_json = input_file.get_map_json(workspace, map)
        assert map_json['layers'][0][
            'url'] == 'http://localhost:8000/geoserver/test_migrate_maps_on_wms_workspace_layer_workspace_wms/ows', map_json
        thumbnail.generate_map_thumbnail(workspace, map, '')
    diffs_after = util.compare_images(expected_file, thumbnail_path)
    shutil.copyfile(thumbnail_path, '/code/tmp/artifacts/upgrade_v1_10_map_thumbnail_after.png')
    assert diffs_after < 1000

    process_client.delete_workspace_layer(layer_workspace, layer)
    process_client.delete_workspace_map(workspace, map)


@pytest.mark.usefixtures('ensure_layman')
def test_migrate_wms_workspace_metadata(ensure_layer):
    def assert_md_keys(layer_info):
        for key in ['comparison_url', 'csw_url', 'identifier', 'record_url']:
            assert key in layer_info['metadata']

    workspace = 'test_migrate_wms_workspace_metadata_workspace'
    layer = 'test_migrate_wms_workspace_metadata_layer'
    ensure_layer(workspace, layer)

    with app.app_context():
        upgrade_v1_10.migrate_layers_to_wms_workspace(workspace)

    wms_workspace = wms.get_geoserver_workspace(workspace)
    wms_old_prefix = f"http://localhost:8000/geoserver/{workspace}/ows"
    wms_new_prefix = f"http://localhost:8000/geoserver/{wms_workspace}/ows"
    csw_prefix = f"http://localhost:3080/csw"

    layer_info = process_client.get_workspace_layer(workspace, layer)
    assert_md_keys(layer_info)

    md_comparison = process_client.get_workspace_layer_metadata_comparison(workspace, layer)
    md_props = md_comparison['metadata_properties']

    csw_src_key = process_client.get_source_key_from_metadata_comparison(md_comparison, csw_prefix)
    assert csw_src_key is not None

    assert md_props['wms_url']['equal'] is False
    assert md_props['wms_url']['equal_or_null'] is False
    assert md_props['wms_url']['values'][csw_src_key].startswith(wms_old_prefix)
    with app.app_context():
        upgrade_v1_10.migrate_metadata_records(workspace)

    layer_info = process_client.get_workspace_layer(workspace, layer)
    assert_md_keys(layer_info)

    md_comparison = process_client.get_workspace_layer_metadata_comparison(workspace, layer)
    md_props = md_comparison['metadata_properties']

    csw_src_key = process_client.get_source_key_from_metadata_comparison(md_comparison, csw_prefix)
    assert csw_src_key is not None
    assert md_props['wms_url']['values'][csw_src_key].startswith(wms_new_prefix)
    for v in md_props['wms_url']['values'].values():
        assert v.startswith(wms_new_prefix)
    assert md_props['wms_url']['equal'] is True
    assert md_props['wms_url']['equal_or_null'] is True
    process_client.delete_workspace_layer(workspace, layer)


@pytest.mark.usefixtures('ensure_layman')
def test_migrate_metadata_records_map():
    workspace = 'test_migrate_metadata_records_map_workspace'
    map = 'test_migrate_metadata_records_map_map'
    process_client.publish_workspace_map(workspace, map)
    with app.app_context():
        upgrade_v1_10.migrate_metadata_records(workspace)
    process_client.delete_workspace_map(workspace, map)


@pytest.mark.usefixtures('ensure_layman')
def test_migrate_input_sld_directory_to_input_style(ensure_layer):
    workspace = 'test_migrate_input_sld_directory_to_input_style_workspace'
    layer = 'test_migrate_input_sld_directory_to_input_style_layer'
    with app.app_context():
        input_sld_dir = os.path.join(layer_fs_util.get_layer_dir(workspace, layer),
                                     'input_sld')
        input_style_dir = os.path.join(layer_fs_util.get_layer_dir(workspace, layer),
                                       'input_style')

        assert input_style_dir == input_style.get_layer_input_style_dir(workspace, layer)

        ensure_layer(workspace, layer)

        assert os.path.exists(input_sld_dir)
        assert not os.path.exists(input_style_dir)
        assert os.path.exists(os.path.join(input_sld_dir, f'{layer}.xml'))

        upgrade_v1_10.migrate_input_sld_directory_to_input_style()

        assert not os.path.exists(input_sld_dir)
        assert os.path.exists(input_style_dir)
        assert os.path.exists(os.path.join(input_style_dir, f'{layer}.xml'))

    process_client.delete_workspace_layer(workspace, layer)


@pytest.mark.usefixtures('ensure_layman', 'publications_constraint')
def test_update_style_type_in_db():
    workspace = 'test_update_style_type_in_db_workspace'
    map = 'test_update_style_type_in_db_map'
    TestLayerDef = namedtuple('TestLayerDef', ['name',
                                               'style_file',
                                               'expected_style',
                                               ])
    layers = [TestLayerDef('test_update_style_type_in_db_none_layer',
                           '',
                           'sld',
                           ),
              TestLayerDef('test_update_style_type_in_db_sld_layer',
                           'sample/style/generic-blue_sld.xml',
                           'sld',
                           ),
              TestLayerDef('test_update_style_type_in_db_sld110_layer',
                           'sample/style/sld_1_1_0.xml',
                           'sld',
                           ),
              # This should not happened, because before this release, it was not possible to upload QGIS files
              TestLayerDef('test_update_style_type_in_db_qgis_layer',
                           'sample/style/small_layer.qml',
                           'sld',
                           ),
              ]

    process_client.publish_workspace_map(workspace, map)
    for layer in layers:
        process_client.publish_workspace_layer(workspace,
                                               layer.name,
                                               style_file=layer.style_file,
                                               )

    set_column_null = f"""update {DB_SCHEMA}.publications set style_type = null"""

    with app.app_context():
        db_util.run_statement(set_column_null)
        map_info = map_util.get_map_info(workspace, map)
        assert map_info['style_type'] is None
        for layer in layers:
            layer_info = layer_util.get_layer_info(workspace, layer.name)
            assert layer_info['style_type'] is None

        upgrade_v1_10.update_style_type_in_db()

        map_info = map_util.get_map_info(workspace, map)
        assert map_info['style_type'] is None
        for layer in layers:
            layer_info = layer_util.get_layer_info(workspace, layer.name)
            assert layer_info['style_type'] == layer.expected_style

    process_client.delete_workspace_map(workspace, map)
    for layer in layers:
        process_client.delete_workspace_layer(workspace,
                                              layer.name,
                                              )
