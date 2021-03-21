import os
from flask import Blueprint, jsonify

from layman import upgrade

bp = Blueprint('rest_about', __name__)


def get_version_from_txt():
    file_path = '/code/version.txt'
    version, release_date = None, None
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            version = f.readline().strip()
            release_date = f.readline().strip()
    return version, release_date


def clean_version(version):
    if version[0] == 'v':
        version = version[1:]
    return version


@bp.route('/version', methods=['GET'])
def get_version():
    version, release_date = get_version_from_txt()
    data_version = upgrade.get_current_data_version()
    result = {'about': {'applications': {'layman': {'version': clean_version(version),
                                                    'release-timestamp': release_date,
                                                    },
                                         'layman-test-client': {'version': clean_version(os.environ['LAYMAN_CLIENT_VERSION']),
                                                                },

                                         },
                        'data': {'layman': {'last-migration': f'{data_version[0]}.{data_version[1]}.{data_version[2]}-{data_version[3]}',
                                            },
                                 },
                        },
              }
    return jsonify(result), 200
