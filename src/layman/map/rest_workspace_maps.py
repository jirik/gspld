import json
import io

from flask import Blueprint, jsonify, request, current_app as app, g
from werkzeug.datastructures import FileStorage

from layman.http import LaymanError
from layman.util import check_username_decorator, url_for
from layman import authn, util as layman_util
from layman.authn import authenticate, get_authn_username
from layman.authz import authorize_workspace_publications_decorator
from layman.common import redis as redis_util, rest as rest_common
from . import util, MAP_TYPE, MAP_REST_PATH_NAME
from .filesystem import input_file, uuid

bp = Blueprint('rest_workspace_maps', __name__)


@bp.before_request
@check_username_decorator
@authenticate
@authorize_workspace_publications_decorator
def before_request():
    pass


@bp.after_request
def after_request(response):
    layman_util.check_deprecated_url(response)
    return response


@bp.route(f"/{MAP_REST_PATH_NAME}", methods=['GET'])
def get(workspace):
    app.logger.info(f"GET Maps, user={g.user}")

    user = get_authn_username()
    return rest_common.get_publications(MAP_TYPE, user, request_args=request.args, workspace=workspace)


@bp.route(f"/{MAP_REST_PATH_NAME}", methods=['POST'])
def post(workspace):
    app.logger.info(f"POST Maps, user={g.user}")

    # FILE
    if 'file' in request.files and not request.files['file'].filename == '':
        file = request.files["file"]
    else:
        raise LaymanError(1, {'parameter': 'file'})
    file_json = util.check_file(file)

    # NAME
    unsafe_mapname = request.form.get('name', '')
    if len(unsafe_mapname) == 0:
        unsafe_mapname = input_file.get_unsafe_mapname(file_json)
    mapname = util.to_safe_map_name(unsafe_mapname)
    util.check_mapname(mapname)
    info = util.get_map_info(workspace, mapname)
    if info:
        raise LaymanError(24, {'mapname': mapname})

    # TITLE
    if len(request.form.get('title', '')) > 0:
        title = request.form['title']
    elif len(file_json.get('title', '')) > 0:
        title = file_json['title']
    else:
        title = mapname

    # DESCRIPTION
    if len(request.form.get('description', '')) > 0:
        description = request.form['description']
    else:
        description = file_json.get('abstract', '')

    mapurl = url_for('rest_workspace_map.get', mapname=mapname, workspace=workspace)

    redis_util.create_lock(workspace, MAP_TYPE, mapname, 29, request.method)

    try:
        map_result = {
            'name': mapname,
            'url': mapurl,
        }

        actor_name = authn.get_authn_username()

        kwargs = {
            'title': title,
            'description': description,
            'actor_name': actor_name
        }

        rest_common.setup_post_access_rights(request.form, kwargs, actor_name)
        util.pre_publication_action_check(workspace,
                                          mapname,
                                          kwargs,
                                          )
        # register map uuid
        uuid_str = uuid.assign_map_uuid(workspace, mapname)
        kwargs['uuid'] = uuid_str

        map_result.update({
            'uuid': uuid_str,
        })

        file = FileStorage(
            io.BytesIO(json.dumps(file_json).encode()),
            file.filename
        )
        input_file.save_map_files(
            workspace, mapname, [file])

        util.post_map(
            workspace,
            mapname,
            kwargs,
            'layman.map.filesystem.input_file'
        )
    except Exception as e:
        try:
            if util.is_map_chain_ready(workspace, mapname):
                redis_util.unlock_publication(workspace, MAP_TYPE, mapname)
        finally:
            redis_util.unlock_publication(workspace, MAP_TYPE, mapname)
        raise e

    # app.logger.info('uploaded map '+mapname)
    return jsonify([map_result]), 200


@bp.route(f"/{MAP_REST_PATH_NAME}", methods=['DELETE'])
def delete(workspace):
    app.logger.info(f"DELETE Maps, user={g.user}")

    infos = layman_util.delete_publications(workspace,
                                            MAP_TYPE,
                                            29,
                                            util.is_map_chain_ready,
                                            util.abort_map_chain,
                                            util.delete_map,
                                            request.method,
                                            'rest_workspace_map.get',
                                            'mapname',
                                            )

    return infos, 200
