import os

from layman.uuid import register_publication_uuid, delete_publication_uuid
from . import util


PUBLICATION_SUBFILE = 'uuid.txt'


def get_publication_info(publ_type, username, publication_name):
    uuid_str = get_publication_uuid(publ_type, username, publ_type, publication_name)
    if uuid_str is not None:
        return {
            'uuid': uuid_str,
        }
    else:
        return {}


def delete_publication(publ_type, username, publication_name):
    uuid_str = get_publication_uuid(publ_type, username, publ_type, publication_name)
    if uuid_str is not None:
        delete_publication_uuid(username, publ_type, publication_name, uuid_str)
    util.delete_publication_subfile(publ_type, username, publication_name, PUBLICATION_SUBFILE)


def get_publication_uuid(publ_type, username, publication_type, publication_name):
    if publication_type != publ_type:
        raise Exception(f'Unknown publication type {publication_type} for type {publ_type}')
    uuid_path = get_publication_uuid_file(publ_type, username, publication_name)
    if not os.path.exists(uuid_path):
        return None
    else:
        with open(uuid_path, "r") as uuid_file:
            uuid_str = uuid_file.read().strip()
            return uuid_str


def get_publication_uuid_file(publ_type, username, publication_name):
    uuid_file = os.path.join(util.get_publication_dir(publ_type, username, publication_name),
                             PUBLICATION_SUBFILE)
    return uuid_file


def assign_publication_uuid(publ_type, username, publication_name, uuid_str=None):
    uuid_str = register_publication_uuid(username, publ_type, publication_name, uuid_str)
    uuid_path = get_publication_uuid_file(publ_type, username, publication_name)
    util.ensure_publication_dir(publ_type, username, publication_name)
    with open(uuid_path, "w") as uuid_file:
        uuid_file.write(uuid_str)
    return uuid_str


def update_publication(publ_type, username, publication_name, publication_info):
    if 'uuid' in publication_info:
        new_uuid = publication_info['uuid']
        old_uuid = get_publication_uuid(publ_type, username, publ_type, publication_name)
        if old_uuid is not None:
            if old_uuid != new_uuid:
                raise Exception(
                    f'Publication {username}/{publ_type}/{publication_name} already has UUID {old_uuid} that differs from updated UUID {new_uuid}')
        elif new_uuid is not None:
            assign_publication_uuid(publ_type, username, publication_name, new_uuid)


