import logging

from db import util as db_util
from geoserver import util as gs_util
from layman import settings
from layman.common import geoserver as gs_common

DB_SCHEMA = settings.LAYMAN_PRIME_SCHEMA

logger = logging.getLogger(__name__)


def initialize_data_versioning():
    logger.info(f'    Starting - data versioning initialization')

    sql_create_table = f'''CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.data_version
    (
        major_version integer not null,
        minor_version integer not null,
        patch_version integer not null,
        migration integer not null
    )
    TABLESPACE pg_default;'''
    db_util.run_statement(sql_create_table)

    # This table should have only one row and now should have none, otherwise something is wrong.
    sql_select_count = f'''select count(*) from {DB_SCHEMA}.data_version'''
    row_count = db_util.run_query(sql_select_count)[0][0]
    assert row_count == 0

    # Set initialization value to 0
    sql_insert = f'''insert into {DB_SCHEMA}.data_version (major_version, minor_version, patch_version, migration) values (1, 9, 0, 0);'''
    db_util.run_statement(sql_insert)

    logger.info(f'    DONE - data versioning initialization')


# repair for issue #200
def geoserver_everyone_rights_repair():
    logger.info(f'    Starting - access rights EVERYONE is not propagated to GeoServer for authenticated users')
    select_layers = f"select w.name, p.name " \
                    f"from {DB_SCHEMA}.publications p inner join {DB_SCHEMA}.workspaces w on w.id = p.id_workspace " \
                    f"where p.type = 'layman.layer' "
    publication_infos = db_util.run_query(select_layers)
    select_rights = f"""select (select rtrim(concat(case when u.id is not null then w.name || ',' end,
                            string_agg(w2.name, ',') || ',',
                            case when p.everyone_can_read then '{settings.RIGHTS_EVERYONE_ROLE}' || ',' end
                            ), ',')
        from _prime_schema.rights r inner join
             _prime_schema.users u2 on r.id_user = u2.id inner join
             _prime_schema.workspaces w2 on w2.id = u2.id_workspace
        where r.id_publication = p.id
          and r.type = %s) can_read_users
from _prime_schema.workspaces w  inner join
     _prime_schema.publications p on p.id_workspace = w.id
                           and p.type = 'layman.layer' left join
     _prime_schema.users u on u.id_workspace = w.id
where w.name = %s
  and p.name = %s"""
    for (workspace, publication_name) in publication_infos:
        for right_type in ['read', 'write']:
            users_roles = db_util.run_query(select_rights, (right_type, workspace, publication_name))[0]
            security_roles = gs_common.layman_users_to_geoserver_roles(users_roles)
            logger.info(f'    Setting security roles for: ({workspace}/{publication_name}).{right_type} '
                        f'to ({security_roles}) from layman roles ({users_roles})')
            gs_util.ensure_layer_security_roles(workspace, publication_name, security_roles, right_type[0], settings.LAYMAN_GS_AUTH)

    logger.info(f'    DONE - access rights EVERYONE is not propagated to GeoServer for authenticated users')


def geoserver_remove_users_for_public_workspaces():
    logger.info(f'    Starting - delete unnecessary users and roles created for public workspaces')
    sql_select_public_workspaces = f'''
        select w.name from {DB_SCHEMA}.workspaces w
        where NOT EXISTS(select 0 FROM {DB_SCHEMA}.USERS u where u.id_workspace = w.id)'''
    public_workspaces = db_util.run_query(sql_select_public_workspaces)
    auth = settings.LAYMAN_GS_AUTH
    for (workspace, ) in public_workspaces:
        logger.info(f'      Delete user and role for workspace {workspace}')
        role = gs_util.username_to_rolename(workspace)
        gs_util.delete_user_role(workspace, role, auth)
        gs_util.delete_user_role(workspace, settings.LAYMAN_GS_ROLE, auth)
        gs_util.delete_role(role, auth)
        gs_util.delete_user(workspace, auth)

    logger.info(f'    DONE - delete unnecessary users and roles created for public workspaces')
