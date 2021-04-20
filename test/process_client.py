import io
import time
import os
import logging
import json
from functools import partial
from collections import namedtuple
import xml.etree.ElementTree as ET
import requests

from layman import app
from layman.util import url_for
from layman.layer.geoserver import wfs, wms
from layman.http import LaymanError

logger = logging.getLogger(__name__)

ISS_URL_HEADER = 'AuthorizationIssUrl'
TOKEN_HEADER = 'Authorization'

layer_keys_to_check = ['db_table', 'wms', 'wfs', 'thumbnail', 'file', 'metadata']
map_keys_to_check = ['thumbnail', 'file', 'metadata']


LAYER_TYPE = 'layman.layer'
MAP_TYPE = 'layman.map'


PUBLICATION_TYPES = [
    LAYER_TYPE,
    MAP_TYPE,
]


PublicationTypeDef = namedtuple('PublicationTypeDef', ['url_param_name',
                                                       'get_publications_url',
                                                       'post_workspace_publication_url',
                                                       'patch_workspace_publication_url',
                                                       'get_workspace_publications_url',
                                                       'get_workspace_publication_url',
                                                       'delete_workspace_publication_url',
                                                       'delete_workspace_publications_url',
                                                       'keys_to_check',
                                                       'source_path',
                                                       'get_workspace_metadata_comparison_url',
                                                       ])
PUBLICATION_TYPES_DEF = {MAP_TYPE: PublicationTypeDef('mapname',
                                                      'rest_maps.get',
                                                      'rest_workspace_maps.post',
                                                      'rest_workspace_map.patch',
                                                      'rest_workspace_maps.get',
                                                      'rest_workspace_map.get',
                                                      'rest_workspace_map.delete_map',
                                                      'rest_workspace_maps.delete',
                                                      map_keys_to_check,
                                                      'sample/layman.map/small_map.json',
                                                      'rest_workspace_map_metadata_comparison.get',
                                                      ),
                         LAYER_TYPE: PublicationTypeDef('layername',
                                                        'rest_layers.get',
                                                        'rest_workspace_layers.post',
                                                        'rest_workspace_layer.patch',
                                                        'rest_workspace_layers.get',
                                                        'rest_workspace_layer.get',
                                                        'rest_workspace_layer.delete_layer',
                                                        'rest_workspace_layers.delete',
                                                        layer_keys_to_check,
                                                        'sample/layman.layer/small_layer.geojson',
                                                        'rest_workspace_layer_metadata_comparison.get',
                                                        ),
                         }


def check_response_keys(keys_to_check, response):
    return response.status_code == 200 and all(
        'status' not in response.json()[k] for k in keys_to_check
    )


def wait_for_rest(url, max_attempts, sleeping_time, check_response, headers=None):
    headers = headers or None
    r = requests.get(url, headers=headers, timeout=5)

    attempts = 1
    while not check_response(r):
        time.sleep(sleeping_time)
        r = requests.get(url, headers=headers, timeout=5)
        attempts += 1
        if attempts > max_attempts:
            logger.error(f"r.status_code={r.status_code}\nrltest={r.text}")
            raise Exception('Max attempts reached!')


def raise_layman_error(response, status_codes_to_skip=None):
    status_codes_to_skip = status_codes_to_skip or set()
    status_codes_to_skip.add(200)
    if 400 <= response.status_code < 500 and response.status_code not in status_codes_to_skip:
        details = json.loads(response.text)
        raise LaymanError(details['code'],
                          details.get('detail'),
                          http_code=response.status_code,
                          sub_code=details.get('sub_code'))
    if response.status_code not in status_codes_to_skip:
        logger.error(f'raise_layman_error: response.status_code={response.status_code}, response.text={response.text}')
        response.raise_for_status()
    assert response.status_code in status_codes_to_skip, f"response.status_code={response.status_code}\nresponse.text={response.text}"
    assert 'Deprecation' not in response.headers, f'This is deprecated URL! Use new one. headers={response.headers}'


def patch_workspace_publication_without_wait(publication_type,
                                             username,
                                             name,
                                             file_paths=None,
                                             headers=None,
                                             access_rights=None,
                                             title=None,
                                             style_file=None,
                                             ):
    headers = headers or {}
    file_paths = file_paths or []
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]
    if style_file:
        assert publication_type == LAYER_TYPE

    with app.app_context():
        r_url = url_for(publication_type_def.patch_workspace_publication_url,
                        username=username,
                        **{publication_type_def.url_param_name: name})

    for fp in file_paths:
        assert os.path.isfile(fp), fp
    files = []
    try:
        files = [('file', (os.path.basename(fp), open(fp, 'rb'))) for fp in file_paths]
        data = dict()
        if access_rights and access_rights.get('read'):
            data["access_rights.read"] = access_rights['read']
        if access_rights and access_rights.get('write'):
            data["access_rights.write"] = access_rights['write']
        if title:
            data['title'] = title
        if style_file:
            files.append(('style', (os.path.basename(style_file), open(style_file, 'rb'))))

        r = requests.patch(r_url,
                           files=files,
                           headers=headers,
                           data=data)
        raise_layman_error(r)
    finally:
        for fp in files:
            fp[1][1].close()
    return r.json()


def patch_workspace_publication(publication_type,
                                username,
                                name,
                                file_paths=None,
                                headers=None,
                                access_rights=None,
                                title=None,
                                style_file=None,
                                check_response_fn=None,
                                ):
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]
    check_response_fn = check_response_fn or partial(check_response_keys, publication_type_def.keys_to_check)
    r = publish_workspace_publication_without_wait(publication_type,
                                                   username,
                                                   name,
                                                   file_paths,
                                                   headers,
                                                   access_rights,
                                                   title,
                                                   style_file,
                                                   )
    with app.app_context():
        url = url_for(publication_type_def.get_workspace_publication_url,
                      username=username,
                      **{publication_type_def.url_param_name: name})
    wait_for_rest(url, 30, 0.5, check_response_fn, headers=headers)
    wfs.clear_cache(username)
    wms.clear_cache(username)
    return r.json()


def patch_publications(publications):
    for publication in publications:
        patch_workspace_publication_without_wait(**publication)
    for publication in publications:
        publication_type_def = PUBLICATION_TYPES_DEF[publication['publication_type']]
        check_response_fn = publication.get('check_response_fn') or partial(check_response_keys, publication_type_def.keys_to_check)
        with app.app_context():
            url = url_for(publication_type_def.get_workspace_publication_url,
                          username=publication['username'],
                          **{publication_type_def.url_param_name: publication['name']})
        wait_for_rest(url, 30, 0.5, check_response_fn, headers=publication.get('headers'))
        wfs.clear_cache(publication['username'])
        wms.clear_cache(publication['username'])


patch_workspace_map = partial(patch_workspace_publication, MAP_TYPE)
patch_workspace_layer = partial(patch_workspace_publication, LAYER_TYPE)


def ensure_workspace_publication(publication_type,
                                 username,
                                 name,
                                 headers=None,
                                 access_rights=None,
                                 ):
    headers = headers or {}

    r = get_workspace_publications(publication_type, username, headers=headers, )
    publication_obj = next((publication for publication in r.json() if publication['name'] == name), None)
    if r.status_code == 200 and publication_obj:
        patch_needed = False
        if access_rights is not None:
            if 'read' in access_rights and set(access_rights['read'].split(',')) != set(publication_obj['access_rights']['read']):
                patch_needed = True
            if 'write' in access_rights and set(access_rights['write'].split(',')) != set(publication_obj['access_rights']['write']):
                patch_needed = True
        if patch_needed:
            result = patch_workspace_publication(publication_type, username, name, access_rights=access_rights, headers=headers)
        else:
            result = None
    else:
        result = publish_workspace_publication(publication_type, username, name, access_rights=access_rights, headers=headers)
    return result


ensure_workspace_layer = partial(ensure_workspace_publication, LAYER_TYPE)
ensure_workspace_map = partial(ensure_workspace_publication, MAP_TYPE)


def publish_workspace_publication_without_wait(publication_type,
                                               username,
                                               name,
                                               file_paths=None,
                                               headers=None,
                                               access_rights=None,
                                               title=None,
                                               style_file=None,
                                               description=None,
                                               ):
    title = title or name
    headers = headers or {}
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]
    file_paths = file_paths or [publication_type_def.source_path, ]
    if style_file:
        assert publication_type == LAYER_TYPE

    with app.app_context():
        r_url = url_for(publication_type_def.post_workspace_publication_url, username=username)

    for fp in file_paths:
        assert os.path.isfile(fp), fp
    files = []
    try:
        files = [('file', (os.path.basename(fp), open(fp, 'rb'))) for fp in file_paths]
        data = {'name': name,
                'title': title,
                }
        if access_rights and access_rights.get('read'):
            data["access_rights.read"] = access_rights['read']
        if access_rights and access_rights.get('write'):
            data["access_rights.write"] = access_rights['write']
        if style_file:
            files.append(('style', (os.path.basename(style_file), open(style_file, 'rb'))))
        if description:
            data['description'] = description
        r = requests.post(r_url,
                          files=files,
                          data=data,
                          headers=headers)
        raise_layman_error(r)
        assert r.json()[0]['name'] == name

    finally:
        for fp in files:
            fp[1][1].close()
    return r


def publish_workspace_publication(publication_type,
                                  username,
                                  name,
                                  file_paths=None,
                                  headers=None,
                                  access_rights=None,
                                  title=None,
                                  style_file=None,
                                  description=None,
                                  check_response_fn=None,
                                  ):
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]
    check_response_fn = check_response_fn or partial(check_response_keys, publication_type_def.keys_to_check)
    r = publish_workspace_publication_without_wait(publication_type,
                                                   username,
                                                   name,
                                                   file_paths,
                                                   headers,
                                                   access_rights,
                                                   title,
                                                   style_file,
                                                   description,
                                                   )
    with app.app_context():
        url = url_for(publication_type_def.get_workspace_publication_url,
                      username=username,
                      **{publication_type_def.url_param_name: name})
    wait_for_rest(url, 30, 0.5, check_response_fn, headers=headers)
    return r.json()[0]


publish_workspace_map = partial(publish_workspace_publication, MAP_TYPE)
publish_workspace_layer = partial(publish_workspace_publication, LAYER_TYPE)


def publish_publications(publications):
    for publication in publications:
        publish_workspace_publication_without_wait(**publication)
    for publication in publications:
        publication_type_def = PUBLICATION_TYPES_DEF[publication['publication_type']]
        check_response_fn = publication.get('check_response_fn') or partial(check_response_keys, publication_type_def.keys_to_check)
        with app.app_context():
            url = url_for(publication_type_def.get_workspace_publication_url,
                          username=publication['username'],
                          **{publication_type_def.url_param_name: publication['name']})
        wait_for_rest(url, 30, 0.5, check_response_fn, headers=publication.get('headers'))


def get_workspace_publications_response(publication_type, workspace, headers=None, query_params=None, ):
    headers = headers or {}
    query_params = query_params or {}
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]

    with app.app_context():
        r_url = url_for(publication_type_def.get_workspace_publications_url, username=workspace)
    r = requests.get(r_url, headers=headers, params=query_params)
    raise_layman_error(r)
    return r


def get_workspace_publications(publication_type, workspace, headers=None, query_params=None, ):
    return get_workspace_publications_response(publication_type, workspace, headers, query_params,).json()


get_workspace_maps = partial(get_workspace_publications, MAP_TYPE)
get_workspace_layers = partial(get_workspace_publications, LAYER_TYPE)


def get_publications_response(publication_type, headers=None, query_params=None):
    headers = headers or {}
    query_params = query_params or {}
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]

    with app.app_context():
        r_url = url_for(publication_type_def.get_publications_url)
    r = requests.get(r_url, headers=headers, params=query_params)
    raise_layman_error(r)
    return r


def get_publications(publication_type, headers=None, query_params=None):
    return get_publications_response(publication_type, headers, query_params).json()


get_maps = partial(get_publications, MAP_TYPE)
get_layers = partial(get_publications, LAYER_TYPE)


def get_workspace_publication(publication_type, username, name, headers=None, ):
    headers = headers or {}
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]

    with app.app_context():
        r_url = url_for(publication_type_def.get_workspace_publication_url,
                        username=username,
                        **{publication_type_def.url_param_name: name})
    r = requests.get(r_url, headers=headers)
    raise_layman_error(r)
    return r.json()


get_workspace_map = partial(get_workspace_publication, MAP_TYPE)
get_workspace_layer = partial(get_workspace_publication, LAYER_TYPE)


def get_workspace_layer_style(workspace, layer, headers=None):
    with app.app_context():
        r_url = url_for('rest_workspace_layer_style.get',
                        username=workspace,
                        layername=layer)
    r = requests.get(r_url, headers=headers)
    raise_layman_error(r)
    return ET.parse(io.BytesIO(r.content))


def finish_delete(username, url, headers, skip_404=False, ):
    r = requests.delete(url, headers=headers)
    status_codes_to_skip = {404} if skip_404 else set()
    raise_layman_error(r, status_codes_to_skip)
    wfs.clear_cache(username)
    wms.clear_cache(username)
    return r.json()


def delete_workspace_publication(publication_type, username, name, headers=None, skip_404=False, ):
    headers = headers or {}
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]

    with app.app_context():
        r_url = url_for(publication_type_def.delete_workspace_publication_url,
                        username=username,
                        **{publication_type_def.url_param_name: name})

    return finish_delete(username, r_url, headers, skip_404=skip_404)


delete_workspace_map = partial(delete_workspace_publication, MAP_TYPE)
delete_workspace_layer = partial(delete_workspace_publication, LAYER_TYPE)


def delete_workspace_publications(publication_type, username, headers=None, ):
    headers = headers or {}
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]

    with app.app_context():
        r_url = url_for(publication_type_def.delete_workspace_publications_url,
                        username=username,
                        )

    return finish_delete(username, r_url, headers, )


delete_workspace_maps = partial(delete_workspace_publications, MAP_TYPE)
delete_workspace_layers = partial(delete_workspace_publications, LAYER_TYPE)


def assert_workspace_publications(publication_type, workspace, expected_publication_names, headers=None):
    r = get_workspace_publications(publication_type, workspace, headers)
    publication_names = [li['name'] for li in r]
    assert set(publication_names) == set(expected_publication_names),\
        f"Publications {expected_publication_names} not equal to {r.text}. publication_type={publication_type}"


assert_workspace_layers = partial(assert_workspace_publications, LAYER_TYPE)
assert_workspace_maps = partial(assert_workspace_publications, MAP_TYPE)


def get_workspace_publication_metadata_comparison(publication_type, workspace, name, headers=None):
    publication_type_def = PUBLICATION_TYPES_DEF[publication_type]
    with app.app_context():
        r_url = url_for(publication_type_def.get_workspace_metadata_comparison_url, **{publication_type_def.url_param_name: name}, username=workspace)
    r = requests.get(r_url, headers=headers)
    raise_layman_error(r)
    return r.json()


get_workspace_layer_metadata_comparison = partial(get_workspace_publication_metadata_comparison, LAYER_TYPE)
get_workspace_map_metadata_comparison = partial(get_workspace_publication_metadata_comparison, MAP_TYPE)


def reserve_username(username, headers=None):
    headers = headers or {}
    with app.app_context():
        r_url = url_for('rest_current_user.patch')
    data = {
        'username': username,
    }
    r = requests.patch(r_url, headers=headers, data=data)
    raise_layman_error(r)
    claimed_username = r.json()['username']
    assert claimed_username == username


def get_current_user(headers=None):
    headers = headers or {}
    with app.app_context():
        r_url = url_for('rest_current_user.get')
    r = requests.get(r_url, headers=headers)
    r.raise_for_status()
    return r.json()


def ensure_reserved_username(username, headers=None):
    headers = headers or {}
    current_user = get_current_user(headers=headers)
    if 'username' not in current_user:
        reserve_username(username, headers=headers)
    else:
        assert current_user['username'] == username


def get_authz_headers(username):
    return {f'{ISS_URL_HEADER}': 'http://localhost:8082/o/oauth2/authorize',
            f'{TOKEN_HEADER}': f'Bearer {username}',
            }


def get_source_key_from_metadata_comparison(md_comparison, url_prefix):
    return next((
        k for k, v in md_comparison['metadata_sources'].items()
        if v['url'].startswith(url_prefix)
    ), None)
