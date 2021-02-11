import os

from layman import patch_mode
from layman.layer import qgis

PATCH_MODE = patch_mode.DELETE_IF_DEPENDANT
VERSION = "1.3.0"


def get_publication_uuid(username, publication_type, publication_name):
    return None


def get_metadata_comparison(username, layername):
    pass


def pre_publication_action_check(username, layername):
    pass


def get_layer_info(username, layername):
    input_file_dir = qgis.get_layer_dir(username, layername)
    result = {}
    if os.path.exists(input_file_dir):
        result = {'name': layername}
    return result


def post_layer(username, layername):
    qgis.ensure_layer_dir(username, layername)


def patch_layer(username, layername):
    pass


def delete_layer(username, layername):
    qgis.delete_layer_dir(username, layername)