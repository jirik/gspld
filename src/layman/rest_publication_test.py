import time

from test import process_client
import pytest

from layman import LaymanError, settings
from layman.common import empty_method_returns_true
from layman.common.micka import util as micka_util

db_schema = settings.LAYMAN_PRIME_SCHEMA


@pytest.mark.parametrize('publ_type', process_client.PUBLICATION_TYPES)
@pytest.mark.usefixtures('ensure_layman')
def test_wrong_post(publ_type):
    def check_response(exception):
        assert exception.value.http_code == 400
        assert exception.value.code == 43
        assert exception.value.message == 'Wrong access rights.'

    workspace = 'test_wrong_post_workspace'
    publication = 'test_wrong_post_publication'

    with pytest.raises(LaymanError) as exc_info:
        process_client.publish_workspace_publication(publ_type, workspace, publication, access_rights={'read': 'EVRBODY'}, )
    check_response(exc_info)

    with pytest.raises(LaymanError) as exc_info:
        process_client.publish_workspace_publication(publ_type, workspace, publication, access_rights={'write': 'EVRBODY'}, )
    check_response(exc_info)

    with pytest.raises(LaymanError) as exc_info:
        process_client.publish_workspace_publication(publ_type, workspace, publication, access_rights={'read': 'EVRBODY', 'write': 'EVRBODY'}, )
    check_response(exc_info)

    process_client.publish_workspace_publication(publ_type, workspace, publication)

    with pytest.raises(LaymanError) as exc_info:
        process_client.patch_workspace_publication(publ_type, workspace, publication, access_rights={'read': 'EVRBODY'}, )
    check_response(exc_info)

    with pytest.raises(LaymanError) as exc_info:
        process_client.patch_workspace_publication(publ_type, workspace, publication, access_rights={'write': 'EVRBODY'}, )
    check_response(exc_info)

    with pytest.raises(LaymanError) as exc_info:
        process_client.patch_workspace_publication(publ_type, workspace, publication, access_rights={'read': 'EVRBODY', 'write': 'EVRBODY'}, )
    check_response(exc_info)

    process_client.patch_workspace_publication(publ_type, workspace, publication)

    process_client.delete_workspace_publication(publ_type, workspace, publication)


class TestSoapClass:
    username = 'test_rest_soap_user'
    publ_name_prefix = 'test_rest_soap_'
    authz_headers = process_client.get_authz_headers(username)
    access_rights_rowo = {'read': f"{username}", 'write': f"{username}"}
    access_rights_rewo = {'read': f"{username},EVERYONE", 'write': f"{username}"}
    access_rights_rewe = {'read': f"{username},EVERYONE", 'write': f"{username},EVERYONE"}
    publication_type = None
    publication_name = None

    @pytest.fixture(scope='class')
    def reserve_username(self):
        process_client.ensure_reserved_username(self.username, headers=self.authz_headers)
        yield

    @pytest.fixture()
    def clear_data(self):
        yield
        process_client.delete_workspace_publication(self.publication_type,
                                                    self.username,
                                                    self.publication_name,
                                                    headers=self.authz_headers)

    @pytest.mark.flaky(reruns=5, reruns_delay=2)
    @pytest.mark.usefixtures('liferay_mock', 'ensure_layman', 'reserve_username', 'clear_data')
    @pytest.mark.parametrize('params_and_expected_list', [
        # (input access rights, expected public visibility of metadata record)
        [(access_rights_rowo, False), (access_rights_rewe, True)],
        [(access_rights_rewo, True)],
        [(access_rights_rewe, True), (access_rights_rowo, False)],
    ])
    @pytest.mark.parametrize('publ_type', process_client.PUBLICATION_TYPES)
    def test_soap_authz(self, publ_type, params_and_expected_list):
        username = self.username
        publ_name_prefix = self.publ_name_prefix
        authz_headers = self.authz_headers

        post_method = process_client.publish_workspace_publication
        patch_method = process_client.patch_workspace_publication
        publ_name = f"{publ_name_prefix}{publ_type.split('.')[-1]}"
        self.publication_type = publ_type
        self.publication_name = publ_name

        for idx, (access_rights, anonymous_visibility) in enumerate(params_and_expected_list):
            write_method = patch_method if idx > 0 else post_method

            write_method(publ_type,
                         username,
                         publ_name,
                         headers=authz_headers,
                         access_rights=access_rights)

            publ_uuid = process_client.get_workspace_publication(publ_type, username, publ_name, headers=authz_headers)['uuid']
            publ_muuid = f"m-{publ_uuid}"
            assert micka_util.get_number_of_records(publ_muuid, use_authn=True) > 0
            anon_number_of_records = micka_util.get_number_of_records(publ_muuid, use_authn=False)
            assert bool(anon_number_of_records) == anonymous_visibility, \
                f"muuid={publ_muuid}, access_rights={access_rights}, number_of_records={anon_number_of_records}"


@pytest.mark.parametrize('publ_type', process_client.PUBLICATION_TYPES)
@pytest.mark.usefixtures('ensure_layman')
def test_get_publication_laymen_status(publ_type):
    workspace = 'test_get_publication_laymen_status_workspace'
    publication = 'test_get_publication_laymen_status_publication'

    process_client.publish_workspace_publication(publ_type, workspace, publication, check_response_fn=empty_method_returns_true, file_paths=['sample/data/zero_length_attribute.geojson'])

    time.sleep(5)
    info = process_client.get_workspace_publication(publ_type, workspace, publication,)
    assert 'layman_metadata' in info, f'info={info}'
    assert 'publication_status' in info['layman_metadata'], f'info={info}'
    print(f'\n\ntest_get_publication_laymen_status: publication_status={info["layman_metadata"]["publication_status"]}\n\n')

    process_client.delete_workspace_publication(publ_type, workspace, publication)
