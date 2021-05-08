import datetime
from test import process_client, assert_util, data as test_data
import pytest

from db import util as db_util
from geoserver import util as gs_util
from layman import app, settings
from layman.common.filesystem import uuid as uuid_common
from layman.common.micka import util as micka_util
from layman.layer import geoserver as gs_layer, NO_STYLE_DEF, db
from layman.layer.geoserver import wms
from layman.layer.prime_db_schema import table as prime_db_schema_table
from layman.uuid import generate_uuid
from . import upgrade_v1_12

db_schema = settings.LAYMAN_PRIME_SCHEMA


@pytest.fixture()
def ensure_layer():
    def ensure_layer_internal(workspace, layer):
        access_rights = {'read': [settings.RIGHTS_EVERYONE_ROLE], 'write': [settings.RIGHTS_EVERYONE_ROLE], }
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
            file_path = '/code/sample/layman.layer/small_layer.geojson'
            uuid_common.assign_publication_uuid('layman.layer', workspace, layer, uuid_str=uuid_str)
            db.ensure_workspace(workspace)
            db.import_layer_vector_file(workspace, layer, file_path, None)
            # wfs
            created = gs_util.ensure_workspace(workspace, settings.LAYMAN_GS_AUTH)
            if created:
                gs_util.create_db_store(workspace, settings.LAYMAN_GS_AUTH, db_schema=workspace, pg_conn=settings.PG_CONN)
            gs_layer.publish_layer_from_db(workspace, layer, layer, layer, None, workspace)
            # wms
            geoserver_workspace = wms.get_geoserver_workspace(workspace)
            created = gs_util.ensure_workspace(geoserver_workspace, settings.LAYMAN_GS_AUTH)
            if created:
                gs_util.create_db_store(geoserver_workspace, settings.LAYMAN_GS_AUTH, db_schema=workspace, pg_conn=settings.PG_CONN)
            gs_layer.publish_layer_from_db(workspace, layer, layer, layer, None, geoserver_workspace)

            md_path = '/code/src/layman/upgrade/upgrade_v1_12_test_layer_metadata.xml'
            with open(md_path, 'r') as template_file:
                md_template = template_file.read()
            record = md_template.format(uuid=uuid_str,
                                        md_date_stamp=datetime.date.today().strftime('%Y-%m-%d'),
                                        publication_date=datetime.date.today().strftime('%Y-%m-%d'),
                                        workspace=workspace,
                                        layer=layer,
                                        )
            micka_util.soap_insert_record(record, is_public=True)

    yield ensure_layer_internal


@pytest.mark.usefixtures('ensure_layman')
def test_adjust_prime_db_schema_for_last_change_search():
    workspace = 'test_adjust_prime_db_schema_for_last_change_search_workspace'
    layer = 'test_adjust_prime_db_schema_for_last_change_search_layer'
    map = 'test_adjust_prime_db_schema_for_last_change_search_map'

    timestamp1 = datetime.datetime.now(datetime.timezone.utc)
    process_client.publish_workspace_layer(workspace, layer)
    process_client.publish_workspace_map(workspace, map)
    timestamp2 = datetime.datetime.now(datetime.timezone.utc)
    with app.app_context():
        statement = f'ALTER TABLE {db_schema}.publications ALTER COLUMN updated_at DROP NOT NULL;'
        db_util.run_statement(statement)
        statement = f'update {db_schema}.publications set updated_at = null;'
        db_util.run_statement(statement)

        query = f'select p.id from {db_schema}.publications p where p.updated_at is not null;'
        results = db_util.run_query(query)
        assert not results, results

        upgrade_v1_12.adjust_data_for_last_change_search()

        query = f'''
select p.updated_at
from {db_schema}.publications p inner join
     {db_schema}.workspaces w on p.id_workspace = w.id
where w.name = %s
  and p.type = %s
  and p.name = %s
;'''
        results = db_util.run_query(query, (workspace, 'layman.layer', layer))
        assert len(results) == 1 and len(results[0]) == 1, results
        layer_updated_at = results[0][0]
        assert timestamp1 < layer_updated_at < timestamp2

        results = db_util.run_query(query, (workspace, 'layman.map', map))
        assert len(results) == 1 and len(results[0]) == 1, results
        map_updated_at = results[0][0]
        assert timestamp1 < map_updated_at < timestamp2

        assert layer_updated_at < map_updated_at

    process_client.delete_workspace_layer(workspace, layer)
    process_client.delete_workspace_map(workspace, map)


@pytest.mark.usefixtures('ensure_layman')
def test_migrate_layer_metadata(ensure_layer):
    def assert_md_keys(layer_info):
        for key in ['comparison_url', 'csw_url', 'identifier', 'record_url']:
            assert key in layer_info['metadata']

    def assert_csw_value(md_comparison, prop_key, exp_value):
        csw_prefix = f"http://localhost:3080/csw"
        csw_src_key = process_client.get_source_key_from_metadata_comparison(md_comparison, csw_prefix)
        assert csw_src_key is not None
        md_props = md_comparison['metadata_properties']
        assert md_props[prop_key]['equal'] is True
        assert md_props[prop_key]['equal_or_null'] is True
        assert md_props[prop_key]['values'][csw_src_key] == exp_value

    workspace = 'test_migrate_layer_metadata_workspace'
    layer = 'test_migrate_layer_metadata_layer'
    ensure_layer(workspace, layer)

    layer_info = process_client.get_workspace_layer(workspace, layer)
    assert_md_keys(layer_info)

    md_comparison = process_client.get_workspace_layer_metadata_comparison(workspace, layer)
    exp_wms_url = f"http://localhost:8000/geoserver/{workspace}_wms/ows?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0"
    assert_csw_value(md_comparison, 'wms_url', exp_wms_url)
    exp_wfs_url = f"http://localhost:8000/geoserver/{workspace}/wfs?SERVICE=WFS&REQUEST=GetCapabilities&VERSION=2.0.0"
    assert_csw_value(md_comparison, 'wfs_url', exp_wfs_url)

    with app.app_context():
        upgrade_v1_12.migrate_layer_metadata(workspace)

    layer_info = process_client.get_workspace_layer(workspace, layer)
    assert_md_keys(layer_info)

    md_comparison = process_client.get_workspace_layer_metadata_comparison(workspace, layer)
    exp_wms_url = f"{exp_wms_url}&LAYERS={layer}"
    assert_csw_value(md_comparison, 'wms_url', exp_wms_url)
    exp_wfs_url = f"{exp_wfs_url}&LAYERS={layer}"
    assert_csw_value(md_comparison, 'wfs_url', exp_wfs_url)

    process_client.delete_workspace_layer(workspace, layer)


@pytest.mark.usefixtures('ensure_layman')
def test_adjust_prime_db_schema_for_bbox_search():
    workspace = 'test_adjust_prime_db_schema_for_bbox_search_workspace'
    layer = 'test_adjust_prime_db_schema_for_bbox_search_layer'
    map = 'test_adjust_prime_db_schema_for_bbox_search_map'

    expected_bbox_layer = test_data.SMALL_LAYER_BBOX
    expected_bbox_map = test_data.SMALL_MAP_BBOX

    process_client.publish_workspace_layer(workspace, layer)
    process_client.publish_workspace_map(workspace, map)
    with app.app_context():
        statement = f'ALTER TABLE {db_schema}.publications ALTER COLUMN bbox DROP NOT NULL;'
        db_util.run_statement(statement)
        statement = f'update {db_schema}.publications set bbox = null;'
        db_util.run_statement(statement)

        query = f'select p.id from {db_schema}.publications p where p.bbox is not null;'
        results = db_util.run_query(query)
        assert not results, results

        upgrade_v1_12.adjust_data_for_bbox_search()

        for publication_type, publication, expected_bbox in [('layman.layer', layer, expected_bbox_layer),
                                                             ('layman.map', map, expected_bbox_map)]:
            query = f'''
            select ST_XMIN(p.bbox),
                   ST_YMIN(p.bbox),
                   ST_XMAX(p.bbox),
                   ST_YMAX(p.bbox)
            from {db_schema}.publications p inner join
                 {db_schema}.workspaces w on p.id_workspace = w.id
            where w.name = %s
              and p.type = %s
              and p.name = %s
            ;'''
            results = db_util.run_query(query, (workspace, publication_type, publication))
            assert len(results) == 1 and len(results[0]) == 4, results
            bbox = results[0]
            assert_util.assert_same_bboxes(bbox, expected_bbox, 0.000001)

    process_client.delete_workspace_layer(workspace, layer)
