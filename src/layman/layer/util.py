from functools import wraps, partial
import re

from flask import current_app, request, g

from layman import LaymanError, patch_mode, util as layman_util
from layman.util import call_modules_fn, get_providers_from_source_names, get_internal_sources, \
    to_safe_name, url_for
from layman import celery as celery_util, common
from layman.common import redis as redis_util, tasks as tasks_util, metadata as metadata_common
from layman.common.util import PUBLICATION_NAME_PATTERN, clear_publication_info
from . import get_layer_sources, LAYER_TYPE, get_layer_type_def

LAYERNAME_PATTERN = PUBLICATION_NAME_PATTERN
ATTRNAME_PATTERN = PUBLICATION_NAME_PATTERN

FLASK_PROVIDERS_KEY = f'{__name__}:PROVIDERS'
FLASK_SOURCES_KEY = f'{__name__}:SOURCES'
FLASK_INFO_KEY = f'{__name__}:LAYER_INFO'


def to_safe_layer_name(value):
    return to_safe_name(value, 'layer')


def check_layername_decorator(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        check_layername(request.view_args['layername'])
        result = f(*args, **kwargs)
        return result

    return decorated_function


def info_decorator(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        workspace = request.view_args['workspace']
        layername = request.view_args['layername']
        info = get_complete_layer_info(workspace, layername)
        assert FLASK_INFO_KEY not in g, g.get(FLASK_INFO_KEY)
        # current_app.logger.info(f"Setting INFO of layer {username}:{layername}")
        g.setdefault(FLASK_INFO_KEY, info)
        result = f(*args, **kwargs)
        return result

    return decorated_function


def check_layername(layername):
    if not re.match(LAYERNAME_PATTERN, layername):
        raise LaymanError(2, {'parameter': 'layername', 'expected': LAYERNAME_PATTERN})


def get_sources():
    key = FLASK_SOURCES_KEY
    if key not in current_app.config:
        current_app.config[key] = get_internal_sources(LAYER_TYPE)
    return current_app.config[key]


def get_providers():
    key = FLASK_PROVIDERS_KEY
    if key not in current_app.config:
        current_app.config[key] = get_providers_from_source_names(get_layer_sources())
    return current_app.config[key]


def check_new_layername(workspace, layername):
    check_layername(layername)
    providers = get_providers()
    call_modules_fn(providers, 'check_new_layername', [workspace, layername])


def get_layer_info(workspace, layername, context=None):
    partial_info = layman_util.get_publication_info(workspace, LAYER_TYPE, layername, context)

    chain_info = _get_layer_chain(workspace, layername)
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
            # current_app.logger.info(f"Exception catched: {str(res_exc)}")
            if isinstance(res_exc, LaymanError):
                source_state.update({
                    'error': res_exc.to_dict()
                })
        if task_name not in TASKS_TO_LAYER_INFO_KEYS:
            continue
        for layerinfo_key in TASKS_TO_LAYER_INFO_KEYS[task_name]:
            if layerinfo_key not in partial_info or not res.successful():
                partial_info[layerinfo_key] = source_state

    return partial_info


def get_complete_layer_info(username=None, layername=None, cached=False):
    assert (username is not None and layername is not None) or cached
    if cached:
        return g.get(FLASK_INFO_KEY)
    partial_info = get_layer_info(username, layername)

    if not any(partial_info):
        raise LaymanError(15, {'layername': layername})

    complete_info = {
        'name': layername,
        'url': url_for('rest_workspace_layer.get', layername=layername, workspace=username),
        'title': layername,
        'description': '',
        'wms': {
            'status': 'NOT_AVAILABLE'
        },
        'wfs': {
            'status': 'NOT_AVAILABLE'
        },
        'thumbnail': {
            'status': 'NOT_AVAILABLE'
        },
        'file': {
            'status': 'NOT_AVAILABLE'
        },
        'db_table': {
            'status': 'NOT_AVAILABLE'
        },
        'metadata': {
            'status': 'NOT_AVAILABLE'
        },
        'style': {
            'status': 'NOT_AVAILABLE'
        },
    }

    complete_info.update(partial_info)

    complete_info = clear_publication_info(complete_info)

    complete_info['sld'] = complete_info['style']
    return complete_info


def pre_publication_action_check(workspace, layername, task_options):
    # sync processing
    sources = get_sources()
    call_modules_fn(sources, 'pre_publication_action_check', [workspace, layername], kwargs=task_options)


def post_layer(workspace, layername, task_options, start_async_at):
    # sync processing
    sources = get_sources()
    call_modules_fn(sources, 'post_layer', [workspace, layername], kwargs=task_options)

    post_tasks = tasks_util.get_task_methods(get_layer_type_def(), workspace, layername, task_options, start_async_at)
    post_chain = tasks_util.get_chain_of_methods(workspace, layername, post_tasks, task_options, 'layername')
    # res = post_chain.apply_async()
    res = post_chain()

    celery_util.set_publication_chain_info(workspace, LAYER_TYPE, layername, post_tasks, res)


def patch_layer(workspace, layername, task_options, stop_sync_at, start_async_at):
    # sync processing
    sources = get_sources()
    stop_idx = next((idx for idx, s in enumerate(sources) if s.__name__ == stop_sync_at), len(sources))
    sources = sources[:stop_idx]
    call_modules_fn(sources, 'patch_layer', [workspace, layername], kwargs=task_options)

    patch_tasks = tasks_util.get_task_methods(get_layer_type_def(), workspace, layername, task_options, start_async_at)
    patch_chain = tasks_util.get_chain_of_methods(workspace, layername, patch_tasks, task_options, 'layername')
    # res = patch_chain.apply_async()
    res = patch_chain()

    celery_util.set_publication_chain_info(workspace, LAYER_TYPE, layername, patch_tasks, res)


TASKS_TO_LAYER_INFO_KEYS = {
    'layman.layer.filesystem.input_chunk.refresh': ['file'],
    'layman.layer.db.table.refresh': ['db_table'],
    'layman.layer.geoserver.wfs.refresh': ['wfs'],
    'layman.layer.geoserver.wms.refresh': ['wms'],
    'layman.layer.geoserver.sld.refresh': ['style'],
    'layman.layer.filesystem.thumbnail.refresh': ['thumbnail'],
    'layman.layer.micka.soap.refresh': ['metadata'],
}


def patch_after_wfst(workspace, layername, **kwargs):
    layman_util.patch_after_wfst(workspace, LAYER_TYPE, layername, **kwargs)


def delete_layer(workspace, layername, source=None, http_method='delete'):
    sources = get_sources()
    source_idx = next((
        idx for idx, m in enumerate(sources) if m.__name__ == source
    ), 0)
    end_idx = None if source_idx == 0 else source_idx - 1
    sources = sources[:end_idx:-1]
    if http_method == common.REQUEST_METHOD_PATCH:
        sources = [
            m for m in sources
            if m.PATCH_MODE == patch_mode.DELETE_IF_DEPENDANT
        ]
    # print(f"delete_layer {username}.{layername} using {len(sources)} sources: {[s.__name__ for s in sources]}")

    result = {}
    results = call_modules_fn(sources, 'delete_layer', [workspace, layername])
    for r in results.values():
        if r is not None:
            result.update(r)
    celery_util.delete_publication(workspace, LAYER_TYPE, layername)
    return result


def _get_layer_chain(username, layername):
    chain_info = celery_util.get_publication_chain_info(username, LAYER_TYPE, layername)
    return chain_info


def abort_layer_chain(username, layername):
    celery_util.abort_publication_chain(username, LAYER_TYPE, layername)


def is_layer_chain_ready(username, layername):
    chain_info = _get_layer_chain(username, layername)
    return chain_info is None or celery_util.is_chain_ready(chain_info)


lock_decorator = redis_util.create_lock_decorator(LAYER_TYPE, 'layername', 19, is_layer_chain_ready)


def layer_info_to_metadata_properties(info):
    result = {
        'title': info['title'],
        'identifier': {
            'identifier': info['url'],
            'label': info['name'],
        },
        'abstract': info['description'],
        'graphic_url': info.get('thumbnail', {}).get('url', None),
        'wms_url': info.get('wms', {}).get('url', None),
        'wfs_url': info.get('wfs', {}).get('url', None),
        'layer_endpoint': info['url'],
    }
    return result


def get_metadata_comparison(workspace, layername):
    layman_info = get_complete_layer_info(cached=True)
    layman_props = layer_info_to_metadata_properties(layman_info)
    all_props = {
        f"{layman_props['layer_endpoint']}": layman_props,
    }
    sources = get_sources()
    partial_infos = call_modules_fn(sources, 'get_metadata_comparison', [workspace, layername])
    for pi in partial_infos.values():
        if pi is not None:
            all_props.update(pi)

    return metadata_common.transform_metadata_props_to_comparison(all_props)


get_syncable_prop_names = partial(metadata_common.get_syncable_prop_names, LAYER_TYPE)


def get_same_or_missing_prop_names(username, layername):
    md_comparison = get_metadata_comparison(username, layername)
    prop_names = get_syncable_prop_names()
    return metadata_common.get_same_or_missing_prop_names(prop_names, md_comparison)
