from functools import wraps, partial
import json
import os
import re
from jsonschema import validate, Draft7Validator
from flask import current_app, request, g

from layman import LaymanError, util as layman_util, celery as celery_util
from layman.authn.filesystem import get_authn_info
from layman.common.micka import util as micka_util
from layman.common import redis as redis_util, tasks as tasks_util, metadata as metadata_common
from layman.common.util import PUBLICATION_NAME_PATTERN, clear_publication_info
from layman.util import call_modules_fn, get_providers_from_source_names, get_internal_sources, \
    to_safe_name, url_for
from . import get_map_sources, MAP_TYPE, get_map_type_def
from .filesystem import input_file
from .micka import csw
from .micka.csw import map_json_to_operates_on, map_json_to_epsg_codes


MAPNAME_PATTERN = PUBLICATION_NAME_PATTERN


FLASK_PROVIDERS_KEY = f'{__name__}:PROVIDERS'
FLASK_SOURCES_KEY = f'{__name__}:SOURCES'
FLASK_INFO_KEY = f'{__name__}:MAP_INFO'


def to_safe_map_name(value):
    return to_safe_name(value, 'map')


def check_mapname_decorator(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        check_mapname(request.view_args['mapname'])
        result = f(*args, **kwargs)
        return result

    return decorated_function


def info_decorator(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        workspace = request.view_args['workspace']
        mapname = request.view_args['mapname']
        info = get_complete_map_info(workspace, mapname)
        assert FLASK_INFO_KEY not in g, g.get(FLASK_INFO_KEY)
        # current_app.logger.info(f"Setting INFO of map {username}:{mapname}")
        g.setdefault(FLASK_INFO_KEY, info)
        result = f(*args, **kwargs)
        return result

    return decorated_function


def check_mapname(mapname):
    if not re.match(MAPNAME_PATTERN, mapname):
        raise LaymanError(2, {'parameter': 'mapname',
                              'expected': MAPNAME_PATTERN})


def get_sources():
    key = FLASK_SOURCES_KEY
    if key not in current_app.config:
        current_app.config[key] = get_internal_sources(MAP_TYPE)
    return current_app.config[key]


def get_providers():
    key = FLASK_PROVIDERS_KEY
    if key not in current_app.config:
        current_app.config[key] = get_providers_from_source_names(get_map_sources())
    return current_app.config[key]


TASKS_TO_MAP_INFO_KEYS = {
    'layman.map.filesystem.thumbnail.refresh': ['thumbnail'],
    'layman.map.micka.soap.refresh': ['metadata'],
}


def get_map_info(workspace, mapname, context=None):
    partial_info = layman_util.get_publication_info(workspace, MAP_TYPE, mapname, context)

    chain_info = _get_map_chain(workspace, mapname)
    if chain_info is None or celery_util.is_chain_successful(chain_info):
        return partial_info

    failed = False
    for res in chain_info['by_order']:
        task_name = next(k for k, v in chain_info['by_name'].items() if v == res)
        source_state = {
            'status': res.state if not failed else 'NOT_AVAILABLE'
        }
        if res.failed():
            failed = True
            res_exc = res.get(propagate=False)
            if isinstance(res_exc, LaymanError):
                source_state.update({
                    'error': res_exc.to_dict()
                })
        if task_name not in TASKS_TO_MAP_INFO_KEYS:
            continue
        for mapinfo_key in TASKS_TO_MAP_INFO_KEYS[task_name]:
            if mapinfo_key not in partial_info or not res.successful():
                partial_info[mapinfo_key] = source_state

    return partial_info


def pre_publication_action_check(workspace, mapname, task_options):
    # sync processing
    sources = get_sources()
    call_modules_fn(sources, 'pre_publication_action_check', [workspace, mapname], kwargs=task_options)


def post_map(workspace, mapname, task_options, start_at):
    # sync processing
    sources = get_sources()
    call_modules_fn(sources, 'post_map', [workspace, mapname], kwargs=task_options)

    # async processing
    post_tasks = tasks_util.get_task_methods(get_map_type_def(), workspace, mapname, task_options, start_at)
    post_chain = tasks_util.get_chain_of_methods(workspace, mapname, post_tasks, task_options, 'mapname')
    # res = post_chain.apply_async()
    res = post_chain()

    celery_util.set_publication_chain_info(workspace, MAP_TYPE, mapname, post_tasks, res)


def patch_map(workspace, mapname, task_options, start_at):
    # sync processing
    sources = get_sources()
    call_modules_fn(sources, 'patch_map', [workspace, mapname], kwargs=task_options)

    # async processing
    patch_tasks = tasks_util.get_task_methods(get_map_type_def(), workspace, mapname, task_options, start_at)
    patch_chain = tasks_util.get_chain_of_methods(workspace, mapname, patch_tasks, task_options, 'mapname')
    # res = patch_chain.apply_async()
    res = patch_chain()

    celery_util.set_publication_chain_info(workspace, MAP_TYPE, mapname, patch_tasks, res)


def delete_map(workspace, mapname, kwargs=None):
    sources = get_sources()
    call_modules_fn(sources[::-1], 'delete_map', [workspace, mapname], kwargs=kwargs)
    celery_util.delete_publication(workspace, MAP_TYPE, mapname)


def get_complete_map_info(username=None, mapname=None, cached=False):
    assert (username is not None and mapname is not None) or cached
    if cached:
        return g.get(FLASK_INFO_KEY)
    partial_info = get_map_info(username, mapname)

    if not any(partial_info):
        raise LaymanError(26, {'mapname': mapname})

    complete_info = {
        'name': mapname,
        'url': url_for('rest_workspace_map.get', mapname=mapname, workspace=username),
        'title': mapname,
        'description': '',
        'file': {
            'status': 'NOT_AVAILABLE'
        },
        'thumbnail': {
            'status': 'NOT_AVAILABLE'
        },
        'metadata': {
            'status': 'NOT_AVAILABLE'
        },
    }

    complete_info.update(partial_info)

    complete_info = clear_publication_info(complete_info)

    return complete_info


def check_file(file):
    try:
        file_json = json.load(file)
        schema_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            'schema.draft-07.json'
        )
        with open(schema_path) as schema_file:
            schema_json = json.load(schema_file)
            validator = Draft7Validator(schema_json)
            if not validator.is_valid(file_json):
                errors = [
                    {
                        'message': e.message,
                        'absolute_path': list(e.absolute_path),
                    }
                    for e in validator.iter_errors(file_json)
                ]
                raise LaymanError(2, {
                    'parameter': 'file',
                    'reason': 'JSON not valid against schema layman/map/schema.draft-07.json',
                    'validation-errors': errors,
                })
            validate(instance=file_json, schema=schema_json)
            return file_json

    except ValueError as exc:
        raise LaymanError(2, {
            'parameter': 'file',
            'reason': 'Invalid JSON syntax'
        }) from exc


def _get_map_chain(username, mapname):
    chain_info = celery_util.get_publication_chain_info(username, MAP_TYPE, mapname)
    return chain_info


def abort_map_chain(username, mapname):
    celery_util.abort_publication_chain(username, MAP_TYPE, mapname)


def is_map_chain_ready(username, mapname):
    chain_info = _get_map_chain(username, mapname)
    return chain_info is None or celery_util.is_chain_ready(chain_info)


def get_map_owner_info(username):
    claims = get_authn_info(username).get('claims', {})
    name = claims.get('name', username)
    email = claims.get('email', '')
    result = {
        'name': name,
        'email': email,
    }
    return result


lock_decorator = redis_util.create_lock_decorator(MAP_TYPE, 'mapname', 29, is_map_chain_ready)

get_syncable_prop_names = partial(metadata_common.get_syncable_prop_names, MAP_TYPE)


def map_info_to_metadata_properties(info):
    result = {
        'title': info['title'],
        'identifier': {
            'identifier': info['url'],
            'label': info['name'],
        },
        'abstract': info['description'],
        'graphic_url': info.get('thumbnail', {}).get('url', None),
        'map_endpoint': info['url'],
        'map_file_endpoint': info.get('file', {}).get('url', None),
    }
    return result


def get_bbox_from_json(map_json):
    return float(map_json['extent'][0]), float(map_json['extent'][1]), float(map_json['extent'][2]), float(map_json['extent'][3])


def map_file_to_metadata_properties(map_json, operates_on_muuids_filter):
    result = {
        'title': map_json['title'],
        'abstract': map_json['abstract'],
        'operates_on': map_json_to_operates_on(map_json, operates_on_muuids_filter=operates_on_muuids_filter),
        'extent': list(get_bbox_from_json(map_json)),
        'reference_system': map_json_to_epsg_codes(map_json),
    }
    return result


def get_metadata_comparison(workspace, mapname):
    layman_info = get_complete_map_info(cached=True)
    layman_props = map_info_to_metadata_properties(layman_info)
    all_props = {
        f"{layman_props['map_endpoint']}": layman_props,
    }
    sources = get_sources()
    partial_infos = call_modules_fn(sources, 'get_metadata_comparison', [workspace, mapname])
    for pi in partial_infos.values():
        if pi is not None:
            all_props.update(pi)
    map_json = get_map_file_json(workspace, mapname)
    if map_json:
        soap_operates_on = next(iter(partial_infos[csw].values()))['operates_on'] if partial_infos[csw] else []
        operates_on_muuids_filter = micka_util.operates_on_values_to_muuids(soap_operates_on)
        layman_file_props = map_file_to_metadata_properties(map_json, operates_on_muuids_filter)
        map_file_url = url_for('rest_workspace_map_file.get', mapname=mapname, workspace=workspace)
        all_props[map_file_url] = layman_file_props

    return metadata_common.transform_metadata_props_to_comparison(all_props)


def get_same_or_missing_prop_names(username, mapname):
    md_comparison = get_metadata_comparison(username, mapname)
    prop_names = get_syncable_prop_names()
    return metadata_common.get_same_or_missing_prop_names(prop_names, md_comparison)


def get_map_file_json(username, mapname):
    map_json = input_file.get_map_json(username, mapname)
    if map_json is not None:
        map_json['user'] = get_map_owner_info(username)
        map_json.pop("groups", None)
    return map_json
