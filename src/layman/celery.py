import json
from flask import current_app
from celery.contrib.abortable import AbortableAsyncResult

from layman import settings
from layman.common import redis as redis_util

REDIS_CURRENT_TASK_NAMES = f"{__name__}:CURRENT_TASK_NAMES"
PUBLICATION_CHAIN_INFOS = f'{__name__}:PUBLICATION_TASK_INFOS'
TASK_ID_TO_PUBLICATION = f'{__name__}:TASK_ID_TO_PUBLICATION'


def task_prerun(workspace, _publication_type, publication_name, _task_id, task_name):
    current_app.logger.info(f"PRE task={task_name}, workspace={workspace}, publication_name={publication_name}")
    rds = settings.LAYMAN_REDIS
    key = REDIS_CURRENT_TASK_NAMES
    task_hash = _get_task_hash(task_name, workspace, publication_name)
    rds.sadd(key, task_hash)


def task_postrun(workspace, publication_type, publication_name, task_id, task_name, task_state):
    current_app.logger.info(f"POST task={task_name}, workspace={workspace}, publication_name={publication_name}")
    rds = settings.LAYMAN_REDIS
    key = REDIS_CURRENT_TASK_NAMES
    task_hash = _get_task_hash(task_name, workspace, publication_name)
    rds.srem(key, task_hash)

    key = TASK_ID_TO_PUBLICATION
    hash = task_id
    if rds.hexists(key, hash):
        finnish_publication_task(task_id)
    elif task_state == 'FAILURE':
        chain_info = get_publication_chain_info_dict(workspace, publication_type, publication_name)
        if chain_info is not None:
            last_task_id = chain_info['last']
            finnish_publication_task(last_task_id)


def _get_task_hash(task_name, workspace, publication_name):
    return f"{task_name}:{workspace}:{publication_name}"


def finnish_publication_task(task_id):
    rds = settings.LAYMAN_REDIS
    key = TASK_ID_TO_PUBLICATION
    hash = task_id
    publ_hash = rds.hget(key, hash)
    if publ_hash is None:
        return
    username, publication_type, publication_name = _hash_to_publication(publ_hash)

    chain_info = get_publication_chain_info_dict(username, publication_type, publication_name)
    chain_info['finished'] = True
    set_publication_chain_info_dict(username, publication_type, publication_name, chain_info)

    rds.hdel(key, hash)

    lock = redis_util.get_publication_lock(username, publication_type, publication_name)
    if lock in ['patch', 'post', 'wfst', ]:
        redis_util.unlock_publication(username, publication_type, publication_name)


def _hash_to_publication(hash):
    return hash.split(':')


def is_task_running(task_name, workspace, publication_name=None):
    redis = settings.LAYMAN_REDIS
    key = REDIS_CURRENT_TASK_NAMES
    if publication_name is not None:
        task_hash = _get_task_hash(task_name, workspace, publication_name)
        result = redis.sismember(key, task_hash)
    else:
        hashes = redis.smembers(key)
        result = any((
            h for h in hashes
            if h.startswith(f"{task_name}:{workspace}:")
        ))
    return result


def get_publication_chain_info_dict(workspace, publication_type, publication_name):
    rds = settings.LAYMAN_REDIS
    key = PUBLICATION_CHAIN_INFOS
    hash = _get_publication_hash(workspace, publication_type, publication_name)
    val = rds.hget(key, hash)
    chain_info = json.loads(val) if val is not None else val
    return chain_info


def get_publication_chain_info(workspace, publication_type, publication_name):
    chain_info = get_publication_chain_info_dict(workspace, publication_type, publication_name)
    from layman import celery_app
    if chain_info is not None:
        results = {
            task_id: AbortableAsyncResult(task_id, backend=celery_app.backend)
            for task_id in chain_info['by_order']
        }

        chain_info['by_order'] = [results[task_id] for task_id in chain_info['by_order']]
        chain_info['by_name'] = {
            k: results[task_id] for k, task_id in chain_info['by_name'].items()
        }
        chain_info['last'] = results[chain_info['last']]
    return chain_info


def set_publication_chain_info_dict(workspace, publication_type, publication_name, chain_info):
    rds = settings.LAYMAN_REDIS
    val = json.dumps(chain_info)
    key = PUBLICATION_CHAIN_INFOS
    hash = _get_publication_hash(workspace, publication_type, publication_name)
    rds.hset(key, hash, val)


def set_publication_chain_info(workspace, publication_type, publication_name, tasks, task_result):
    if task_result is None:
        return
    chained_results = [task_result]
    prev_result = task_result
    while prev_result.parent is not None:
        prev_result = prev_result.parent
        chained_results.insert(0, prev_result)
    chain_info = {
        'last': task_result.task_id,
        'by_name': {
            tasks[idx].name: r.task_id for idx, r in enumerate(chained_results)
        },
        'by_order': [r.task_id for r in chained_results],
        'finished': False,
    }
    set_publication_chain_info_dict(workspace, publication_type, publication_name, chain_info)

    rds = settings.LAYMAN_REDIS
    key = TASK_ID_TO_PUBLICATION
    val = _get_publication_hash(workspace, publication_type, publication_name)
    hash = chain_info['last']
    rds.hset(key, hash, val)


def abort_chain(chain_info):
    if chain_info is None or is_chain_ready(chain_info):
        return

    abort_task_chain(chain_info['by_order'], chain_info['by_name'])
    finnish_publication_task(chain_info['last'].task_id)


def abort_task_chain(results_by_order, results_by_name=None):
    results_by_name = results_by_name or {}
    task_results = [r for r in results_by_order if not r.ready()]
    current_app.logger.info(
        f"Aborting chain of {len(results_by_order)} tasks, {len(task_results)} of them are not yet ready.")

    for task_result in task_results:
        task_name = next((k for k, v in results_by_name.items() if v == task_result), None)
        current_app.logger.info(
            f'processing result {task_name} {task_result.id} {task_result.state} {task_result.ready()} {task_result.successful()} {task_result.failed()}')
        if task_result.ready():
            continue
        prev_task_state = task_result.state
        current_app.logger.info(f'aborting result {task_name} {task_result.id} with state {task_result.state}')
        task_result.abort()
        assert task_result.state == 'ABORTED'
        if prev_task_state == 'STARTED':
            current_app.logger.info(
                f'waiting for result of {task_name} {task_result.id} with state {task_result.state}')
            # if hangs forever, see comment in src/layman/layer/rest_workspace_test.py::test_post_layers_simple
            task_result.get(propagate=False)
        current_app.logger.info(f'aborted result {task_name} {task_result.id} with state {task_result.state}')


def is_chain_successful(chain_info):
    return chain_info['last'].successful()


def is_chain_failed(chain_info):
    return any(tr.failed() for tr in chain_info['by_order'])


def is_chain_ready(chain_info):
    return is_chain_successful(chain_info) or is_chain_failed(chain_info)


def _get_publication_hash(workspace, publication_type, publication_name):
    hash = f"{workspace}:{publication_type}:{publication_name}"
    return hash


def delete_publication(workspace, publication_type, publication_name):
    chain_info = get_publication_chain_info_dict(workspace, publication_type, publication_name)
    if chain_info is None:
        return
    task_id = chain_info['last']

    rds = settings.LAYMAN_REDIS
    key = PUBLICATION_CHAIN_INFOS
    hash = _get_publication_hash(workspace, publication_type, publication_name)
    rds.hdel(key, hash)

    key = TASK_ID_TO_PUBLICATION
    rds.hdel(key, task_id)


class AbortedException(Exception):
    pass
