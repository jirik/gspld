import sys

del sys.modules['layman']

from layman import app, settings
from .filesystem import input_file, uuid, thumbnail
from .micka import soap
from .prime_db_schema import table as prime_table
from . import util, MAP_TYPE
from layman.util import url_for
from test import flask_client as client_util

client = client_util.client


def test_get_map_infos(client):
    username = 'test_get_map_infos_user'
    mapname = 'test_get_map_infos_layer'
    maptitle = "Test get map infos - map title íářžý"

    client_util.publish_map(username, mapname, client, maptitle)

    result_infos_name = {mapname: {'name': mapname}}
    result_infos_name_title = {mapname: {'name': mapname, 'title': maptitle}}
    result_publication_name = [mapname]

    with app.app_context():
        result_infos_name_title_uuid = {mapname: {'name': mapname,
                                                  'title': maptitle,
                                                  'uuid': uuid.get_map_uuid(username, mapname)}}
        result_infos_all = {mapname: {'name': mapname,
                                      'title': maptitle,
                                      'uuid': uuid.get_map_uuid(username, mapname),
                                      'type': MAP_TYPE,
                                      }}
        result_infos_db = {mapname: {'name': mapname,
                                     'title': maptitle,
                                     'uuid': uuid.get_map_uuid(username, mapname),
                                     'type': MAP_TYPE,
                                     'access_rights': {'read': f'{settings.RIGHTS_EVERYONE_ROLE}',
                                                       'write': f'{settings.RIGHTS_EVERYONE_ROLE}',
                                                       }
                                     }}
        modules = [
            {'name': 'prime_table.table',
             'method_infos': prime_table.get_map_infos,
             'result_infos': result_infos_db,
             'method_publications': prime_table.get_publication_infos,
             },
            {'name': 'filesystem.input_file',
             'method_infos': input_file.get_map_infos,
             'result_infos': result_infos_name_title,
             'method_publications': input_file.get_publication_infos,
             },
            {'name': 'filesystem.uuid',
             'method_infos': uuid.get_map_infos,
             'result_infos': result_infos_name_title_uuid,
             'method_publications': uuid.get_publication_infos,
             },
            {'name': 'filesystem.thumbnail',
             'method_infos': thumbnail.get_map_infos,
             'result_infos': result_infos_name_title,
             'method_publications': thumbnail.get_publication_infos,
             },
            {'name': 'micka.soap',
             'method_infos': soap.get_map_infos,
             'result_infos': {},
             'method_publications': soap.get_publication_infos,
             },
        ]

        for module in modules:
            map_infos = module["method_infos"](username)
            if map_infos and map_infos[mapname] and map_infos[mapname].get("id"):
                del map_infos[mapname]["id"]
            assert map_infos == module["result_infos"],\
                (module["name"], module["method_infos"].__module__, map_infos)
            publication_infos = module["method_publications"](username, "layman.map")
            if publication_infos and publication_infos[mapname] and publication_infos[mapname].get("id"):
                del publication_infos[mapname]["id"]
            assert publication_infos == module["result_infos"],\
                (module["name"], module["method_publications"].__module__, publication_infos)

        map_infos = util.get_map_infos(username)
        del map_infos[mapname]["id"]
        assert map_infos == result_infos_db, map_infos

    client_util.delete_map(username, mapname, client)


def test_get_map_title(client):
    username = 'test_get_map_infos_user'
    maps = [("c_test_get_map_infos_map", "C Test get map infos - map title íářžý"),
            ("a_test_get_map_infos_map", "A Test get map infos - map title íářžý"),
            ("b_test_get_map_infos_map", "B Test get map infos - map title íářžý")
            ]
    sorted_maps = sorted(maps)

    for (name, title) in maps:
        client_util.publish_map(username, name, client, title)

    with app.app_context():
        # maps.GET
        rv = client.get(url_for('rest_maps.get', username=username))
        assert rv.status_code == 200, rv.json

        for i in range(0, len(sorted_maps) - 1):
            assert rv.json[i]["name"] == sorted_maps[i][0]
            assert rv.json[i]["title"] == sorted_maps[i][1]

    for (name, title) in maps:
        client_util.delete_map(username, name, client)
