from collections import defaultdict
from uuid import UUID, uuid4

from flask import current_app
from redis import WatchError

from layman import LaymanError, celery as celery_util, util as layman_util
from layman.common import redis as redis_util
from . import settings

UUID_SET_KEY = f'{__name__}:UUID_SET'
UUID_METADATA_KEY = f'{__name__}:UUID_METADATA:{{uuid}}'
USER_TYPE_NAMES_KEY = f'{__name__}:USER_TYPE_NAMES:{{username}}:{{publication_type}}'


def import_uuids_to_redis():
    current_app.logger.info('Importing UUIDs to REDIS')

    infos = layman_util.get_publication_infos()
    for (workspace, publication_type, publication_name), info in infos.items():
        register_publication_uuid(workspace, publication_type,
                                  publication_name, info["uuid"],
                                  ignore_duplicate=True)

        current_app.logger.info(
            f'Import publication into redis: workspace {workspace}, type {publication_type}, name {publication_name}, uuid {info["uuid"]}')


def generate_uuid():
    return str(uuid4())


def register_publication_uuid(username, publication_type, publication_name, uuid_str=None, ignore_duplicate=False):
    if uuid_str is None:
        uuid_str = generate_uuid()

    user_type_names_key = get_user_type_names_key(username, publication_type)
    uuid_metadata_key = get_uuid_metadata_key(uuid_str)

    with settings.LAYMAN_REDIS.pipeline() as pipe:
        while True:
            try:
                pipe.watch(UUID_SET_KEY, uuid_metadata_key, user_type_names_key)

                if not ignore_duplicate:
                    if pipe.sismember(UUID_SET_KEY, uuid_str):
                        raise LaymanError(23, {'message': f'Redis already contains UUID {uuid_str}'})

                    if pipe.exists(uuid_metadata_key):
                        raise LaymanError(23, {'message': f'Redis already contains metadata of UUID {uuid_str}'})

                    if pipe.hexists(user_type_names_key, publication_name):
                        raise LaymanError(23, {
                            'message': f'Redis already contains publication type/user/name {publication_type}/{username}/{publication_name}'})

                pipe.multi()
                pipe.sadd(UUID_SET_KEY, uuid_str)
                pipe.hmset(
                    uuid_metadata_key,
                    {
                        'username': username,
                        'publication_type': publication_type,
                        'publication_name': publication_name,
                    }
                )
                pipe.hset(
                    user_type_names_key,
                    publication_name,
                    uuid_str
                )
                pipe.execute()
                break
            except WatchError:
                continue

    return uuid_str


def delete_publication_uuid(username, publication_type, publication_name, uuid_str):
    user_type_names_key = get_user_type_names_key(username, publication_type)
    uuid_metadata_key = get_uuid_metadata_key(uuid_str)

    settings.LAYMAN_REDIS.srem(UUID_SET_KEY, uuid_str)
    settings.LAYMAN_REDIS.delete(uuid_metadata_key)
    settings.LAYMAN_REDIS.hdel(user_type_names_key, publication_name)


def get_uuid_metadata_key(uuid_str):
    return UUID_METADATA_KEY.format(uuid=uuid_str)


def get_user_type_names_key(username, publication_type):
    return USER_TYPE_NAMES_KEY.format(
        username=username,
        publication_type=publication_type,
    )


def is_valid_uuid(maybe_uuid_str):
    try:
        UUID(maybe_uuid_str)
    except ValueError:
        return False
    return True


def check_redis_consistency(expected_publ_num_by_type=None):
    # get info from non-redis sources
    infos = layman_util.get_publication_infos()
    num_total_publs = len(infos)
    total_publs = list(infos.keys())

    # publication types and names
    redis = settings.LAYMAN_REDIS
    user_publ_keys = redis.keys(':'.join(USER_TYPE_NAMES_KEY.split(':')[:2]) + ':*')
    uuid_keys = redis.keys(':'.join(UUID_METADATA_KEY.split(':')[:2]) + ':*')
    assert num_total_publs == len(uuid_keys), f"total_publs={total_publs}, uuid_keys={uuid_keys}"

    total_publs_by_type = defaultdict(list)
    for publ in total_publs:
        total_publs_by_type[publ[1]].append((publ[0], publ[2]))

    if expected_publ_num_by_type is not None:
        for publ_type, publ_num in expected_publ_num_by_type.items():
            found_publ_num = len(total_publs_by_type[publ_type])
            assert publ_num == found_publ_num, f"expected {publ_num} of {publ_type}, found {found_publ_num}: {total_publs}"

    num_publ = 0
    for user_publ_key in user_publ_keys:
        num_publ += redis.hlen(user_publ_key)
    assert num_publ == len(uuid_keys)

    # publication uuids
    uuids = redis.smembers(UUID_SET_KEY)
    assert len(uuids) == num_publ

    for uuid_str in uuids:
        assert get_uuid_metadata_key(uuid_str) in uuid_keys

    for uuid_key in uuid_keys:
        uuid_dict = redis.hgetall(uuid_key)
        assert redis.hexists(
            get_user_type_names_key(
                uuid_dict['username'],
                uuid_dict['publication_type']
            ),
            uuid_dict['publication_name'],
        )

    # publication tasks
    chain_infos_len = redis.hlen(celery_util.PUBLICATION_CHAIN_INFOS)
    assert chain_infos_len == len(total_publs), f"task_infos_len={chain_infos_len}, total_publs={total_publs}"

    task_names_tuples = [
        h.split(':') for h in redis.smembers(celery_util.REDIS_CURRENT_TASK_NAMES)
    ]

    for username, publ_type_name, pubname in total_publs:
        chain_info = celery_util.get_publication_chain_info(username, publ_type_name, pubname)
        is_ready = celery_util.is_chain_ready(chain_info)
        assert chain_info['finished'] is is_ready
        assert (next((
            t for t in task_names_tuples
            if t[1] == username and t[2] == pubname and t[0].startswith(publ_type_name)
        ), None) is None) is is_ready, f"{username}, {publ_type_name}, {pubname}: {is_ready}, {task_names_tuples}"
        assert (redis.hget(celery_util.LAST_TASK_ID_IN_CHAIN_TO_PUBLICATION, chain_info['last'].task_id) is None) is is_ready

    # publication locks
    locks = redis.hgetall(redis_util.PUBLICATION_LOCKS_KEY)
    assert len(locks) == len(task_names_tuples), f"{locks} != {task_names_tuples}"
    for k, _ in locks.items():
        username, publication_type, publication_name = k.split(':')
        assert next((
            t for t in task_names_tuples
            if t[1] == username and t[2] == publication_name and t[0].startswith(publication_type)
        ), None) is not None
    return total_publs_by_type
