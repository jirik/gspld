from collections import namedtuple

REQUEST_METHOD_DELETE = 'delete'
REQUEST_METHOD_GET = 'get'
REQUEST_METHOD_PATCH = 'patch'
REQUEST_METHOD_POST = 'post'
REQUEST_METHOD_PUT = 'put'
PUBLICATION_LOCK_CODE_POST = 'post'
PUBLICATION_LOCK_CODE_PATCH = 'patch'
PUBLICATION_LOCK_CODE_DELETE = 'delete'
PUBLICATION_LOCK_CODE_WFST = 'wfst'

InternalSourceTypeDef = namedtuple('InternalSourceTypeDef', ['info_items',
                                                             ])


def empty_method(*_args, **_kwargs):
    pass


def empty_method_returns_none(*_args, **_kwargs):
    return None


def empty_method_returns_dict(*_args, **_kwargs):
    return dict()


def empty_method_returns_true(*_args, **_kwargs):
    return True
