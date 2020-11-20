import json
from flask import after_this_request
from functools import wraps
from layman.common.prime_db_schema import workspaces, users, publications
from layman import util as layman_util


from flask import g, request
import re

from layman import LaymanError, settings
from layman.util import USERNAME_ONLY_PATTERN
from layman.common.util import PUBLICATION_NAME_ONLY_PATTERN


def _get_multi_publication_path_pattern():
    workspace_pattern = r"(?P<workspace>" + USERNAME_ONLY_PATTERN + r")"
    # TODO generate layers|maps automatically from blueprints using settings.PUBLICATION_MODULES
    publ_type_pattern = r"(?P<publication_type>layers|maps)"
    return "^/rest/" + workspace_pattern + "/" + publ_type_pattern


MULTI_PUBLICATION_PATH_PATTERN = re.compile(_get_multi_publication_path_pattern() + r"/?$")
SINGLE_PUBLICATION_PATH_PATTERN = re.compile(
    _get_multi_publication_path_pattern() + r"/(?P<publication_name>" + PUBLICATION_NAME_ONLY_PATTERN + r")(?:/.*)?$"
)


from layman.common import geoserver as gs


def parse_request_path(request_path):
    workspace = None
    publication_type = None
    publication_type_url_prefix = None
    publication_name = None
    m = MULTI_PUBLICATION_PATH_PATTERN.match(request_path)
    if not m:
        m = SINGLE_PUBLICATION_PATH_PATTERN.match(request_path)
    if m:
        workspace = m.group('workspace')
        publication_type_url_prefix = m.group('publication_type')
        publication_name = m.groupdict().get('publication_name', None)
    if publication_type_url_prefix:
        # TODO get it using settings.PUBLICATION_MODULES
        publication_type = {
            'layers': 'layman.layer',
            'maps': 'layman.map',
        }[publication_type_url_prefix]
    if workspace in settings.RESERVED_WORKSPACE_NAMES:
        workspace = None
    return (workspace, publication_type, publication_name)


def authorize(workspace, publication_type, publication_name, request_method, actor_name):
    is_multi_publication_request = not publication_name

    publication_not_found_code = {
        'layman.layer': 15,
        'layman.map': 26,
    }[publication_type]

    if is_multi_publication_request:
        if request_method in ['GET']:
            if not workspaces.get_workspace_infos(workspace):
                raise LaymanError(40)  # User not found
            return
        elif request_method in ['POST']:
            if actor_name == workspace:
                return
            elif ((not users.get_user_infos(workspace))  # public workspace
                    and can_user_publish_in_public_workspace(actor_name)):  # actor can publish in public workspace
                if workspaces.get_workspace_infos(workspace):  # workspaces exists
                    return
                elif can_user_create_public_workspace(actor_name):  # workspaces can be created by actor
                    # raises exception if new workspace is not correct
                    layman_util.check_username(workspace)
                else:
                    raise LaymanError(30)  # unauthorized request
            else:
                raise LaymanError(30)  # unauthorized request
        else:
            raise LaymanError(31, {'method': request_method})  # unsupported method
    else:
        if not workspaces.get_workspace_infos(workspace):
            raise LaymanError(40)  # User not found
        publ_info = publications.get_publication_infos(workspace, publication_type).get(
            (workspace, publication_type, publication_name)
        )
        if not publ_info:
            raise LaymanError(publication_not_found_code)
        user_can_read = is_user_in_access_rule(actor_name, publ_info['access_rights']['read'])
        if request_method in ['GET']:
            if user_can_read:
                return
            else:
                raise LaymanError(publication_not_found_code)
        elif request_method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            if is_user_in_access_rule(actor_name, publ_info['access_rights']['write']):
                return
            elif user_can_read:
                raise LaymanError(30)  # unauthorized request
            else:
                raise LaymanError(publication_not_found_code)
        else:
            raise LaymanError(31, {'method': request_method})  # unsupported method


def authorize_after_multi_get_request(workspace, actor_name, response):
    # print(f"authorize_after_request, status_code = {response.status_code}, workspace={workspace}, actor_name={actor_name}")
    if response.status_code == 200:
        # TODO when GET Layers will return also access rights, use access rights from response to filter publications
        publication_infos = publications.get_publication_infos(workspace_name=workspace)
        # print(f"authorize_after_request, publication_infos = {publication_infos}")
        safe_uuids = [
            publication_info['uuid'] for publication_info in publication_infos.values()
            if is_user_in_access_rule(actor_name, publication_info['access_rights']['read'])
        ]
        # print(f"authorize_after_request, safe_uuids = {safe_uuids}")
        publications_json = json.loads(response.get_data())
        publications_json = [
            publication_json for publication_json in publications_json
            if publication_json['uuid'] in safe_uuids
        ]
        response.set_data(json.dumps(publications_json))
    return response


def get_publication_access_rights(publ_type, username, publication_name):
    # TODO consult with Franta/Raitis not using groups for map JSON anymore
    return {}


def is_user_in_access_rule(username, access_rule_names):
    return settings.RIGHTS_EVERYONE_ROLE in access_rule_names \
        or (username and username in access_rule_names)


def can_user_publish_in_public_workspace(username):
    return is_user_in_access_rule(username, settings.GRANT_PUBLISH_IN_PUBLIC_WORKSPACE)


def can_user_create_public_workspace(username):
    return is_user_in_access_rule(username, settings.GRANT_CREATE_PUBLIC_WORKSPACE)


def can_user_read_publication(username, workspace, publication_type, publication_name):
    publ_info = publications.get_publication_infos(workspace_name=workspace, pub_type=publication_type).get(
        (workspace, publication_type, publication_name)
    )
    return publ_info and is_user_in_access_rule(username, publ_info['access_rights']['read'])


def can_user_write_publication(username, workspace, publication_type, publication_name):
    publ_info = publications.get_publication_infos(workspace_name=workspace, pub_type=publication_type).get(
        (workspace, publication_type, publication_name)
    )
    return publ_info and is_user_in_access_rule(username, publ_info['access_rights']['write'])


def can_i_edit(publ_type, workspace, publication_name):
    actor_name = g.user and g.user.get('username')
    return can_user_write_publication(actor_name, workspace, publ_type, publication_name)


def authorize_decorator(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # print(f"authorize ARGS {args} KWARGS {kwargs}")
        req_path = request.script_root + request.path
        (workspace, publication_type, publication_name) = parse_request_path(req_path)
        if workspace is None or publication_type is None:
            raise Exception(f"Authorization module is unable to authorize path {req_path}")
        actor_name = g.user and g.user.get('username')
        # raises exception in case of unauthorized request
        authorize(workspace, publication_type, publication_name, request.method, actor_name)
        if workspace and publication_type and not publication_name and request.method == 'GET':
            @after_this_request
            def authorize_after_request_tmp(response):
                return authorize_after_multi_get_request(workspace, actor_name, response)
        return f(*args, **kwargs)

    return decorated_function
