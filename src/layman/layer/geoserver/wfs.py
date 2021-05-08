from urllib.parse import urljoin
import requests
from flask import current_app

from geoserver import util as gs_util
from layman import settings, patch_mode
from layman.cache import mem_redis
from layman.common import geoserver as gs_common, empty_method_returns_none, empty_method
from layman.layer.util import is_layer_chain_ready
from layman import util as layman_util
from layman.layer import LAYER_TYPE
from .util import get_gs_proxy_base_url
from . import wms

FLASK_PROXY_KEY = f'{__name__}:PROXY:{{username}}'

PATCH_MODE = patch_mode.DELETE_IF_DEPENDANT
VERSION = '2.0.0'

get_publication_uuid = empty_method_returns_none
pre_publication_action_check = empty_method
post_layer = empty_method


def get_flask_proxy_key(username):
    return FLASK_PROXY_KEY.format(username=username)


def patch_layer(workspace, layername, title, description, access_rights=None):
    gs_util.patch_feature_type(workspace, layername, title=title, description=description, auth=settings.LAYMAN_GS_AUTH)
    clear_cache(workspace)

    if access_rights and access_rights.get('read'):
        security_read_roles = gs_common.layman_users_to_geoserver_roles(access_rights['read'])
        gs_util.ensure_layer_security_roles(workspace, layername, security_read_roles, 'r', settings.LAYMAN_GS_AUTH)

    if access_rights and access_rights.get('write'):
        security_write_roles = gs_common.layman_users_to_geoserver_roles(access_rights['write'])
        gs_util.ensure_layer_security_roles(workspace, layername, security_write_roles, 'w', settings.LAYMAN_GS_AUTH)


def delete_layer(workspace, layername):
    gs_util.delete_feature_type(workspace, layername, settings.LAYMAN_GS_AUTH)
    clear_cache(workspace)

    gs_util.delete_security_roles(f"{workspace}.{layername}.r", settings.LAYMAN_GS_AUTH)
    gs_util.delete_security_roles(f"{workspace}.{layername}.w", settings.LAYMAN_GS_AUTH)
    return {}


def get_wfs_url(workspace, external_url=False):
    base_url = get_gs_proxy_base_url() if external_url else settings.LAYMAN_GS_URL
    return urljoin(base_url, workspace + '/wfs')


def get_wfs_direct(username):
    headers = {
        settings.LAYMAN_GS_AUTHN_HTTP_HEADER_ATTRIBUTE: settings.LAYMAN_GS_USER,
    }
    ows_url = get_wfs_url(username)
    from .util import wfs_direct
    key = get_flask_proxy_key(username)
    redis_obj = settings.LAYMAN_REDIS.hgetall(key)
    string_value = redis_obj['value'] if redis_obj else None
    return wfs_direct(ows_url, xml=string_value, headers=headers)


def get_wfs_proxy(username):
    headers = {
        settings.LAYMAN_GS_AUTHN_HTTP_HEADER_ATTRIBUTE: settings.LAYMAN_GS_USER,
    }
    key = get_flask_proxy_key(username)

    ows_url = get_wfs_url(username)

    def create_string_value():
        r = requests.get(ows_url, params={
            'SERVICE': 'WFS',
            'REQUEST': 'GetCapabilities',
            'VERSION': VERSION,
        }, headers=headers, timeout=5,)
        if r.status_code != 200:
            result = None
            if r.status_code != 404:
                r.raise_for_status()
                raise Exception(f'Status code = {r.status_code}')
        else:
            r.encoding = 'UTF-8'
            result = r.text
        return result

    def mem_value_from_string_value(string_value):
        from .util import wfs_proxy
        wfs_proxy = wfs_proxy(ows_url, xml=string_value, headers=headers)
        return wfs_proxy

    def currently_changing():
        layerinfos = layman_util.get_publication_infos(username, LAYER_TYPE)
        result = any((
            not is_layer_chain_ready(username, layername)
            for (_, _, layername) in layerinfos
        ))
        return result

    wfs_proxy = mem_redis.get(key, create_string_value, mem_value_from_string_value, currently_changing)

    return wfs_proxy


def clear_cache(username):
    key = get_flask_proxy_key(username)
    mem_redis.delete(key)


def get_layer_info(workspace, layername):
    wfs = get_wfs_proxy(workspace)
    if wfs is None:
        return {}
    wfs_proxy_url = get_wfs_url(workspace, external_url=True)

    wfs_layername = f"{workspace}:{layername}"
    if wfs_layername not in wfs.contents:
        return {}
    return {
        'title': wfs.contents[wfs_layername].title,
        'description': wfs.contents[wfs_layername].abstract,
        'wfs': {
            'url': wfs_proxy_url
        },
    }


def get_metadata_comparison(workspace, layername):
    wfs = get_wfs_direct(workspace)
    if wfs is None:
        return {}
    cap_op = wfs.getOperationByName('GetCapabilities')
    wfs_url = next(
        (
            m.get("url")
            for m in (cap_op.methods if cap_op else [])
            if m.get("type").lower() == 'get'
        ), None
    )
    wfs_layername = f"{workspace}:{layername}"
    wfs_layer = wfs.contents.get(wfs_layername, None)
    try:
        title = wfs_layer.title
    except BaseException:
        title = None
    try:
        abstract = wfs_layer.abstract
    except BaseException:
        abstract = None
    try:
        extent = wfs_layer.boundingBox[:-1]
    except BaseException:
        extent = None
    try:
        crs_list = [int(crs.getcode().split(':')[-1]) for crs in wfs_layer.crsOptions]
        crs_list.append(4326)
        crs_list = sorted(list(set(crs_list)))
        reference_system = crs_list
    except BaseException as e:
        current_app.logger.error(e)
        reference_system = None
    props = {
        'wfs_url': wfs_url,
        'title': title,
        'abstract': abstract,
        'extent': extent,
        'reference_system': reference_system,
    }
    # current_app.logger.info(f"props:\n{json.dumps(props, indent=2)}")
    url = get_capabilities_url(workspace)
    return {
        f"{url}": props
    }


def add_capabilities_params_to_url(url):
    params = {'SERVICE': 'WFS', 'REQUEST': 'GetCapabilities', 'VERSION': VERSION}
    url = wms.add_params_to_url(url, params)
    return url


def get_capabilities_url(username):
    url = get_wfs_url(username, external_url=True)
    url = add_capabilities_params_to_url(url)
    return url
