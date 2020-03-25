ERROR_LIST = {
    1: (400, 'Missing parameter'),
    2: (400, 'Wrong parameter value'),
    3: (409, 'File already exists'),
    4: (400, 'Unsupported CRS of data file'),
    5: (400, 'Data file does not contain single layer'),
    6: (500, 'Cannot connect to database'),
    7: (500, 'Database query error'),
    # 8: (409, 'Reserved DB schema name'),
    9: (409, 'DB object already exists'),
    # 10: (409, 'DB schema owned by another than layman user'),
    11: (500, 'Error during import data into DB'),
    # 12: (409, 'GeoServer workspace not assigned to LAYMAN_GS_ROLE'),
    # 13: (409, 'Reserved GeoServer workspace name'),
    14: (400, 'Invalid SLD file'),
    15: (404, 'Layer was not found'),
    16: (404, 'Thumbnail was not found'),
    17: (409, 'Layer already exists'),
    18: (400, 'Missing one or more ShapeFile files.'),
    19: (400, 'Layer is already in process.'),
    20: (400, 'Chunk upload is not active for this layer.'),
    21: (400, 'Unknown combination of resumableFilename and '
              'layman_original_parameter.'),
    22: (400, 'UPLOAD_MAX_INACTIVITY_TIME during upload reached.'),
    23: (409, 'Publication already exists.'),
    24: (409, 'Map already exists'),
    25: (404, 'This endpoint and method are not implemented yet!'),
    26: (404, 'Map was not found'),
    27: (404, 'File was not found'),
    28: (400, 'Zero-length identifier found. Data file probably contains attribute with zero-length name (e.g. empty string).'),
    29: (400, 'Map is already in process.'),
    30: (403, 'Unauthorized access'),
    31: (400, 'Unexpected HTTP method.'),
    32: (403, 'Unsuccessful OAuth2 authentication.'),
    33: (400, 'Authenticated user did not claim any username within Layman yet.'),
    34: (400, 'User already reserved username.'),
    35: (409, 'Username already reserved.'),
    36: (409, 'Metadata record already exists.'),
    37: (400, 'CSW exception.'),
    38: (400, 'Micka HTTP or connection error.'),
    39: (404, 'Metadata record does not exists.'),
}