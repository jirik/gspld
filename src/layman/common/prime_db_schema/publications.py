import logging
import psycopg2.extras

from . import util, workspaces, users, rights
from layman import settings, LaymanError

logger = logging.getLogger(__name__)

DB_SCHEMA = settings.LAYMAN_PRIME_SCHEMA
ROLE_EVERYONE = settings.RIGHTS_EVERYONE_ROLE
psycopg2.extras.register_uuid()


def get_publication_infos(workspace_name=None, pub_type=None):
    sql = f"""with const as (select %s workspace_name, %s pub_type, %s everyone_role)
select p.id as id_publication,
       w.name as workspace_name,
       p.type,
       p.name,
       p.title,
       p.uuid::text,
       (select rtrim(concat(case when u.id is not null then w.name || ',' end,
                            string_agg(w2.name, ',') || ',',
                            case when p.everyone_can_read then c.everyone_role || ',' end
                            ), ',')
        from {DB_SCHEMA}.rights r inner join
             {DB_SCHEMA}.users u2 on r.id_user = u2.id inner join
             {DB_SCHEMA}.workspaces w2 on w2.id = u2.id_workspace
        where r.id_publication = p.id
          and r.type = 'read') can_read_users,
       (select rtrim(concat(case when u.id is not null then w.name || ',' end,
                            string_agg(w2.name, ',') || ',',
                            case when p.everyone_can_read then c.everyone_role || ',' end
                            ), ',')
        from {DB_SCHEMA}.rights r inner join
             {DB_SCHEMA}.users u2 on r.id_user = u2.id inner join
             {DB_SCHEMA}.workspaces w2 on w2.id = u2.id_workspace
        where r.id_publication = p.id
          and r.type = 'write') can_write_users
from const c inner join
     {DB_SCHEMA}.workspaces w on (   w.name = c.workspace_name
                                  or c.workspace_name is null) inner join
     {DB_SCHEMA}.publications p on p.id_workspace = w.id
                           and (   p.type = c.pub_type
                                or c.pub_type is null) left join
     {DB_SCHEMA}.users u on u.id_workspace = w.id
;"""
    values = util.run_query(sql, (workspace_name,
                                  pub_type,
                                  ROLE_EVERYONE,
                                  ))
    infos = {(workspace_name,
              layername,
              type,): {'id': id_publication,
                       'name': layername,
                       'title': title,
                       'uuid': uuid,
                       'type': type,
                       'access_rights': {'read': {x.strip() for x in can_read_users.split(',')},
                                         'write': {x.strip() for x in can_write_users.split(',')}}
                       }
             for id_publication, workspace_name, type, layername, title, uuid, can_read_users, can_write_users
             in values}
    return infos


def only_valid_names(users_list):
    usernames_for_chesk = users_list.copy()
    usernames_for_chesk.discard(ROLE_EVERYONE)
    for username in usernames_for_chesk:
        info = users.get_user_infos(username)
        if not info:
            raise LaymanError(43, {f'Not valid username. Username={username}'})


def at_least_one_can_write(can_write):
    if not can_write:
        raise LaymanError(43, {f'At least one user have to have write rights.'})


def who_can_write_can_read(can_read, can_write):
    if ROLE_EVERYONE not in can_read and can_write.difference(can_read):
        raise LaymanError(43, {f'All users who have write rights have to have also read rights. Who is missing={can_write.difference(can_read)}'})


def i_can_still_write(actor_name, can_write):
    if ROLE_EVERYONE not in can_write and actor_name not in can_write:
        raise LaymanError(43, {f'After the operation, the actor has to have write right.'})


def owner_can_still_write(owner,
                          can_write,
                          ):
    if owner and ROLE_EVERYONE not in can_write and owner not in can_write:
        raise LaymanError(43, {f'Owner of the personal workspace have to keep write right.'})


def check_rights_axioms(can_read,
                        can_write,
                        actor_name,
                        owner,
                        can_read_old=None,
                        can_write_old=None):
    if can_read:
        only_valid_names(can_read)
    if can_write:
        only_valid_names(can_write)
        owner_can_still_write(owner, can_write)
        at_least_one_can_write(can_write)
        i_can_still_write(actor_name, can_write)
    if can_read or can_write:
        can_read_check = can_read or can_read_old
        can_write_check = can_write or can_write_old
        who_can_write_can_read(can_read_check, can_write_check)


def check_publication_info(workspace_name, info):
    owner_info = users.get_user_infos(workspace_name).get(workspace_name)
    info["owner"] = owner_info and owner_info["username"]
    try:
        check_rights_axioms(info['access_rights'].get('read'),
                            info['access_rights'].get('write'),
                            info["actor_name"],
                            info["owner"],
                            info['access_rights'].get('read_old'),
                            info['access_rights'].get('write_old'),
                            )
    except LaymanError as exc_info:
        raise LaymanError(43, {'workspace_name': workspace_name,
                               'publication_name': info.get("name"),
                               'access_rights': {
                                   'read': info['access_rights'].get('read'),
                                   'write': info['access_rights'].get('write'), },
                               'actor_name': info.get("actor_name"),
                               'owner': info["owner"],
                               'message': exc_info.data,
                               })


def clear_roles(users_list, workspace_name):
    result_list = users_list.copy()
    result_list.discard(ROLE_EVERYONE)
    user_info = users.get_user_infos(workspace_name)
    if user_info:
        result_list.discard(workspace_name)
    return result_list


def insert_publication(workspace_name, info):
    id_workspace = workspaces.ensure_workspace(workspace_name)
    check_publication_info(workspace_name, info)

    insert_publications_sql = f'''insert into {DB_SCHEMA}.publications as p
        (id_workspace, name, title, type, uuid, everyone_can_read, everyone_can_write) values
        (%s, %s, %s, %s, %s, %s, %s)
returning id
;'''

    data = (id_workspace,
            info.get("name"),
            info.get("title"),
            info.get("publ_type_name"),
            info.get("uuid"),
            ROLE_EVERYONE in info['access_rights']['read'],
            ROLE_EVERYONE in info['access_rights']['write'],
            )
    pub_id = util.run_query(insert_publications_sql, data)[0][0]

    read_users = clear_roles(info['access_rights']['read'], workspace_name)
    write_users = clear_roles(info['access_rights']['write'], workspace_name)
    rights.insert_rights(pub_id,
                         read_users,
                         'read')
    rights.insert_rights(pub_id,
                         write_users,
                         'write')
    return pub_id


def update_publication(workspace_name, info):
    id_workspace = workspaces.get_workspace_infos(workspace_name)[workspace_name]["id"]
    everyone_can_read = None
    everyone_can_write = None
    users_read_add = set()
    users_write_add = set()
    users_read_remove = set()
    users_write_remove = set()
    if info.get("access_rights") and (info["access_rights"].get("read") or info["access_rights"].get("write")):
        info_old = get_publication_infos(workspace_name,
                                         info["publ_type_name"])[(workspace_name,
                                                                  info["name"],
                                                                  info["publ_type_name"])]
        users_read_old = info_old["access_rights"]["read"]
        users_write_old = info_old["access_rights"]["write"]
        info["access_rights"].update({"read_old": users_read_old})
        info["access_rights"].update({"write_old": users_write_old})
        check_publication_info(workspace_name, info)

        # TODO refactor, so read and write are less hardcoded
        if info["access_rights"].get("read"):
            users_read = info["access_rights"].get("read")
            everyone_can_read = ROLE_EVERYONE in users_read
            users_read_clear = clear_roles(users_read, workspace_name)
            users_read_old_clear = clear_roles(users_read_old, workspace_name)
            users_read_add = users_read_clear.difference(users_read_old_clear)
            users_read_remove = users_read_old_clear.difference(users_read_clear)

        if info["access_rights"].get("write"):
            users_write = info["access_rights"].get("write")
            everyone_can_write = ROLE_EVERYONE in users_write
            users_write_clear = clear_roles(users_write, workspace_name)
            users_write_old_clear = clear_roles(users_write_old, workspace_name)
            users_write_add = users_write_clear.difference(users_write_old_clear)
            users_write_remove = users_write_old_clear.difference(users_write_clear)

    update_publications_sql = f'''update {DB_SCHEMA}.publications set
    title = coalesce(%s, title),
    everyone_can_read = coalesce(%s, everyone_can_read),
    everyone_can_write = coalesce(%s, everyone_can_write)
where id_workspace = %s
  and name = %s
  and type = %s
returning id
;'''

    data = (info.get("title"),
            everyone_can_read,
            everyone_can_write,
            id_workspace,
            info.get("name"),
            info.get("publ_type_name"),
            )
    pub_id = util.run_query(update_publications_sql, data)[0][0]

    rights.insert_rights(pub_id, users_read_add, "read")
    rights.insert_rights(pub_id, users_write_add, "write")
    rights.remove_rights(pub_id, users_read_remove, "read")
    rights.remove_rights(pub_id, users_write_remove, "write")

    return pub_id


def delete_publication(workspace_name, name, type):
    workspace_info = workspaces.get_workspace_infos(workspace_name).get(workspace_name)
    if workspace_info:
        id_publication = get_publication_infos(workspace_name, type)[(workspace_name, name, type)]["id"]
        rights.delete_rights_for_publication(id_publication)
        id_workspace = workspace_info["id"]
        sql = f"""delete from {DB_SCHEMA}.publications p where p.id_workspace = %s and p.name = %s and p.type = %s;"""
        util.run_statement(sql, (id_workspace,
                                 name,
                                 type,))
    else:
        logger.warning(f'Deleting publication for NON existing workspace. workspace_name={workspace_name}, pub_name={name}, type={type}')
