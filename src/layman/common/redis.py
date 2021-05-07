from functools import wraps
from flask import request, current_app

from layman import settings, celery as celery_util, common
from layman import LaymanError

PUBLICATION_LOCKS_KEY = f'{__name__}:PUBLICATION_LOCKS'


def create_lock(workspace, publication_type, publication_name, error_code, method):
    method = method.lower()
    solve_locks(workspace, publication_type, publication_name, error_code, method)
    lock_publication(workspace, publication_type, publication_name, method)


def create_lock_decorator(publication_type, publication_name_key, error_code, is_chain_ready_fn):
    def lock_decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            username = request.view_args['workspace']
            publication_name = request.view_args[publication_name_key]
            create_lock(username, publication_type, publication_name, error_code, request.method)
            try:
                result = f(*args, **kwargs)
                if is_chain_ready_fn(username, publication_name):
                    unlock_publication(username, publication_type, publication_name)
            except Exception as e:
                try:
                    if is_chain_ready_fn(username, publication_name):
                        unlock_publication(username, publication_type, publication_name)
                finally:
                    unlock_publication(username, publication_type, publication_name)
                raise e
            return result

        return decorated_function

    return lock_decorator


def get_publication_lock(workspace, publication_type, publication_name):
    rds = settings.LAYMAN_REDIS
    key = PUBLICATION_LOCKS_KEY
    hash = _get_publication_hash(workspace, publication_type, publication_name)
    return rds.hget(key, hash)


def lock_publication(workspace, publication_type, publication_name, lock_method):
    current_app.logger.info(f"Locking {workspace}:{publication_type}:{publication_name} with {lock_method.upper()}")
    rds = settings.LAYMAN_REDIS
    key = PUBLICATION_LOCKS_KEY
    hash = _get_publication_hash(workspace, publication_type, publication_name)
    value = lock_method.lower()
    rds.hset(key, hash, value)


def unlock_publication(workspace, publication_type, publication_name):
    current_app.logger.info(f"Unlocking {workspace}:{publication_type}:{publication_name}")
    rds = settings.LAYMAN_REDIS
    key = PUBLICATION_LOCKS_KEY
    hash = _get_publication_hash(workspace, publication_type, publication_name)
    rds.hdel(key, hash)


def solve_locks(workspace, publication_type, publication_name, error_code, requested_lock):
    current_lock = get_publication_lock(
        workspace,
        publication_type,
        publication_name,
    )
    if current_lock is None:
        return
    if requested_lock not in [common.PUBLICATION_LOCK_CODE_PATCH, common.PUBLICATION_LOCK_CODE_DELETE,
                              common.PUBLICATION_LOCK_CODE_WFST, ]:
        raise Exception(f"Unknown method to check: {requested_lock}")
    if current_lock not in [common.PUBLICATION_LOCK_CODE_PATCH, common.PUBLICATION_LOCK_CODE_DELETE,
                            common.PUBLICATION_LOCK_CODE_POST,
                            common.PUBLICATION_LOCK_CODE_WFST, ]:
        raise Exception(f"Unknown current lock: {current_lock}")
    if current_lock in [common.PUBLICATION_LOCK_CODE_PATCH, common.PUBLICATION_LOCK_CODE_POST, ]:
        if requested_lock in [common.PUBLICATION_LOCK_CODE_PATCH, common.PUBLICATION_LOCK_CODE_POST, ]:
            raise LaymanError(error_code)
    elif current_lock in [common.PUBLICATION_LOCK_CODE_DELETE, ]:
        if requested_lock in [common.PUBLICATION_LOCK_CODE_PATCH, common.PUBLICATION_LOCK_CODE_POST, common.PUBLICATION_LOCK_CODE_WFST, ]:
            raise LaymanError(error_code)
    if requested_lock not in [common.PUBLICATION_LOCK_CODE_DELETE, ]:
        if requested_lock == common.PUBLICATION_LOCK_CODE_WFST:
            raise LaymanError(19, private_data={'can_run_later': True})
        if current_lock == common.PUBLICATION_LOCK_CODE_WFST and requested_lock in [common.REQUEST_METHOD_PATCH, common.REQUEST_METHOD_POST, ]:
            chain_info = celery_util.get_publication_chain_info(workspace, publication_type, publication_name)
            celery_util.abort_chain(chain_info)
            celery_util.push_step_to_run_after_chain(workspace, publication_type, publication_name, 'layman.util::patch_after_wfst')


def _get_publication_hash(workspace, publication_type, publication_name):
    hash = f"{workspace}:{publication_type}:{publication_name}"
    return hash
