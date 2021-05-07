from datetime import datetime, date
import os
from functools import partial
import traceback
from requests.exceptions import HTTPError, ConnectionError
from lxml import etree as ET
from flask import current_app

from layman.common.filesystem.uuid import get_publication_uuid_file
from layman.common.micka import util as common_util
from layman.common import language as common_language, empty_method, empty_method_returns_none, bbox as bbox_util
from layman.layer.filesystem.uuid import get_layer_uuid
from layman.layer import db
from layman.layer.geoserver import wms
from layman.layer.geoserver import wfs
from layman.layer import LAYER_TYPE
from layman import settings, patch_mode, LaymanError, common
from layman.util import url_for, get_publication_info

PATCH_MODE = patch_mode.NO_DELETE
get_publication_uuid = empty_method_returns_none
post_layer = empty_method


def get_metadata_uuid(uuid):
    return f"m-{uuid}" if uuid is not None else None


def get_layer_info(workspace, layername):
    uuid = get_layer_uuid(workspace, layername)
    try:
        csw = common_util.create_csw()
        if uuid is None or csw is None:
            return {}
        muuid = get_metadata_uuid(uuid)
        csw.getrecordbyid(id=[muuid], esn='brief')
    except (HTTPError, ConnectionError):
        current_app.logger.info(traceback.format_exc())
        return {}
    if muuid in csw.records:
        return {
            'metadata': {
                'identifier': muuid,
                'csw_url': settings.CSW_PROXY_URL,
                'record_url': settings.CSW_RECORD_URL.format(identifier=muuid),
                'comparison_url': url_for('rest_workspace_layer_metadata_comparison.get', workspace=workspace, layername=layername),
            }
        }
    return {}


def patch_layer(workspace, layername, metadata_properties_to_refresh, _actor_name=None, create_if_not_exists=True, timeout=5):
    # current_app.logger.info(f"patch_layer metadata_properties_to_refresh={metadata_properties_to_refresh}")
    if len(metadata_properties_to_refresh) == 0:
        return None
    uuid = get_layer_uuid(workspace, layername)
    csw = common_util.create_csw()
    if uuid is None or csw is None:
        return None
    muuid = get_metadata_uuid(uuid)
    el = common_util.get_record_element_by_id(csw, muuid)
    if el is None:
        if create_if_not_exists:
            return csw_insert(workspace, layername)
        return None
    # current_app.logger.info(f"Current element=\n{ET.tostring(el, encoding='unicode', pretty_print=True)}")

    _, prop_values = get_template_path_and_values(workspace, layername, http_method=common.REQUEST_METHOD_PATCH)
    prop_values = {
        k: v for k, v in prop_values.items()
        if k in metadata_properties_to_refresh + ['md_date_stamp']
    }
    # current_app.logger.info(f"patch_layer prop_values={prop_values}")
    basic_template_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), './record-template.xml')
    el = common_util.fill_xml_template_obj(el, prop_values, METADATA_PROPERTIES,
                                           basic_template_path=basic_template_path)
    record = ET.tostring(el, encoding='unicode', pretty_print=True)
    # current_app.logger.info(f"patch_layer record=\n{record}")
    try:
        common_util.csw_update({
            'muuid': muuid,
            'record': record,
        }, timeout=timeout)
    except (HTTPError, ConnectionError) as exc:
        current_app.logger.info(traceback.format_exc())
        raise LaymanError(38) from exc
    return muuid


def delete_layer(workspace, layername):
    uuid = get_layer_uuid(workspace, layername)
    muuid = get_metadata_uuid(uuid)
    if muuid is None:
        return
    try:
        common_util.csw_delete(muuid)
    except (HTTPError, ConnectionError) as exc:
        current_app.logger.info(traceback.format_exc())
        raise LaymanError(38) from exc


def csw_insert(workspace, layername):
    template_path, prop_values = get_template_path_and_values(workspace, layername, http_method='post')
    record = common_util.fill_xml_template_as_pretty_str(template_path, prop_values, METADATA_PROPERTIES)
    try:
        muuid = common_util.csw_insert({
            'record': record
        })
    except (HTTPError, ConnectionError) as exc:
        current_app.logger.info(traceback.format_exc())
        raise LaymanError(38) from exc
    return muuid


def get_template_path_and_values(workspace, layername, http_method=None):
    assert http_method in [common.REQUEST_METHOD_POST, common.REQUEST_METHOD_PATCH]
    publ_info = get_publication_info(workspace, LAYER_TYPE, layername, context={
        'keys': ['title', 'bounding_box', 'description'],
    })
    title = publ_info['title']
    abstract = publ_info.get('description')
    bbox_3857 = publ_info.get('bounding_box')
    if bbox_util.is_empty(bbox_3857):
        bbox_3857 = settings.LAYMAN_DEFAULT_OUTPUT_BBOX
    extent = bbox_util.transform(tuple(bbox_3857), epsg_from=3857, epsg_to=4326)

    uuid_file_path = get_publication_uuid_file(LAYER_TYPE, workspace, layername)
    publ_datetime = datetime.fromtimestamp(os.path.getmtime(uuid_file_path))
    revision_date = datetime.now()
    md_language = next(iter(common_language.get_languages_iso639_2(' '.join([
        title or '',
        abstract or ''
    ]))), None)
    try:
        languages = db.get_text_languages(workspace, layername)
    except LaymanError:
        languages = []
    try:
        scale_denominator = db.guess_scale_denominator(workspace, layername)
    except LaymanError:
        scale_denominator = None

    prop_values = _get_property_values(
        workspace=workspace,
        layername=layername,
        uuid=get_layer_uuid(workspace, layername),
        title=title,
        abstract=abstract or None,
        publication_date=publ_datetime.strftime('%Y-%m-%d'),
        revision_date=revision_date.strftime('%Y-%m-%d'),
        md_date_stamp=date.today().strftime('%Y-%m-%d'),
        identifier=url_for('rest_workspace_layer.get', workspace=workspace, layername=layername),
        identifier_label=layername,
        extent=extent,
        wms_url=wms.get_wms_url(workspace, external_url=True),
        wfs_url=wfs.get_wfs_url(workspace, external_url=True),
        md_organisation_name=None,
        organisation_name=None,
        md_language=md_language,
        languages=languages,
        scale_denominator=scale_denominator,
        epsg_codes=settings.LAYMAN_OUTPUT_SRS_LIST,
    )
    if http_method == common.REQUEST_METHOD_POST:
        prop_values.pop('revision_date', None)
    template_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'record-template.xml')
    return template_path, prop_values


def _get_property_values(
        workspace='browser',
        layername='layer',
        uuid='ca238200-8200-1a23-9399-42c9fca53542',
        title='CORINE - Krajinný pokryv CLC 90',
        abstract=None,
        md_organisation_name=None,
        organisation_name=None,
        publication_date='2007-05-25',
        revision_date='2008-05-25',
        md_date_stamp='2007-05-25',
        identifier='http://www.env.cz/data/corine/1990',
        identifier_label='MZP-CORINE',
        extent=None,  # w, s, e, n
        wms_url="http://www.env.cz/corine/data/download.zip",
        wfs_url="http://www.env.cz/corine/data/download.zip",
        epsg_codes=None,
        scale_denominator=None,
        languages=None,
        md_language=None,
):
    epsg_codes = epsg_codes or [3857, 4326]
    w, s, e, n = extent or [11.87, 48.12, 19.13, 51.59]
    extent = [max(w, -180), max(s, -90), min(e, 180), min(n, 90)]
    languages = languages or []

    result = {
        'md_file_identifier': get_metadata_uuid(uuid),
        'md_language': md_language,
        'md_date_stamp': md_date_stamp,
        'reference_system': epsg_codes,
        'title': title,
        'publication_date': publication_date,
        'revision_date': revision_date,
        'identifier': {
            'identifier': identifier,
            'label': identifier_label,
        },
        'abstract': abstract,
        'graphic_url': url_for('rest_workspace_layer_thumbnail.get', workspace=workspace, layername=layername),
        'extent': extent,

        'wms_url': f"{wms.add_capabilities_params_to_url(wms_url)}&LAYERS={layername}",
        'wfs_url': f"{wfs.add_capabilities_params_to_url(wfs_url)}&LAYERS={layername}",
        'layer_endpoint': url_for('rest_workspace_layer.get', workspace=workspace, layername=layername),
        'scale_denominator': scale_denominator,
        'language': languages,
        'md_organisation_name': md_organisation_name,
        'organisation_name': organisation_name,
    }

    return result


METADATA_PROPERTIES = {
    'md_file_identifier': {
        'xpath_parent': '/gmd:MD_Metadata',
        'xpath_property': './gmd:fileIdentifier',
        'xpath_extract': './gco:CharacterString/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': common_util.adjust_character_string,
    },
    'md_language': {
        'xpath_parent': '/gmd:MD_Metadata',
        'xpath_property': './gmd:language',
        'xpath_extract': './gmd:LanguageCode/@codeListValue',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': common_util.adjust_language,
    },
    'md_organisation_name': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:contact/gmd:CI_ResponsibleParty',
        'xpath_property': './gmd:organisationName',
        'xpath_extract': './gco:CharacterString/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': common_util.adjust_character_string,
    },
    'md_date_stamp': {
        'xpath_parent': '/gmd:MD_Metadata',
        'xpath_property': './gmd:dateStamp',
        'xpath_extract': './gco:Date/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': common_util.adjust_date_string,
    },
    'reference_system': {
        'xpath_parent': '/gmd:MD_Metadata',
        'xpath_property': './gmd:referenceSystemInfo[gmd:MD_ReferenceSystem/gmd:referenceSystemIdentifier/gmd:RS_Identifier/gmd:code/gmx:Anchor[starts-with(@xlink:href, "http://www.opengis.net/def/crs/EPSG/0/")]]',
        'xpath_extract': './gmd:MD_ReferenceSystem/gmd:referenceSystemIdentifier/gmd:RS_Identifier/gmd:code/gmx:Anchor/@xlink:href',
        'xpath_extract_fn': lambda l: int(l[0].rsplit('/')[-1]) if l else None,
        'adjust_property_element': common_util.adjust_reference_system_info,
    },
    'title': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation',
        'xpath_property': './gmd:title',
        'xpath_extract': './gco:CharacterString/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': common_util.adjust_character_string,
    },
    'publication_date': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation',
        'xpath_property': './gmd:date[gmd:CI_Date/gmd:dateType/gmd:CI_DateTypeCode[@codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" and @codeListValue="publication"]]',
        'xpath_extract': './gmd:CI_Date/gmd:date/gco:Date/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': partial(common_util.adjust_date_string_with_type, date_type='publication'),
    },
    'revision_date': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation',
        'xpath_property': './gmd:date[gmd:CI_Date/gmd:dateType/gmd:CI_DateTypeCode[@codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" and @codeListValue="revision"]]',
        'xpath_extract': './gmd:CI_Date/gmd:date/gco:Date/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': partial(common_util.adjust_date_string_with_type, date_type='revision'),
    },
    'identifier': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation',
        'xpath_property': './gmd:identifier',
        'xpath_extract': './gmd:MD_Identifier/gmd:code/gmx:Anchor/@xlink:href',
        'xpath_extract_fn': lambda l: {
            'identifier': l[0],
            'label': l[0].getparent().text,
        } if l else None,
        'adjust_property_element': common_util.adjust_identifier_with_label,
    },
    'abstract': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification',
        'xpath_property': './gmd:abstract',
        'xpath_extract': './gco:CharacterString/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': common_util.adjust_character_string,
    },
    'organisation_name': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:pointOfContact/gmd:CI_ResponsibleParty',
        'xpath_property': './gmd:organisationName',
        'xpath_extract': './gco:CharacterString/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': common_util.adjust_character_string,
    },
    'graphic_url': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification',
        'xpath_property': './gmd:graphicOverview[gmd:MD_BrowseGraphic/gmd:fileName/gco:CharacterString]',
        'xpath_extract': './gmd:MD_BrowseGraphic/gmd:fileName/gco:CharacterString/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': common_util.adjust_graphic_url,
    },
    'scale_denominator': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:spatialResolution/gmd:MD_Resolution/gmd:equivalentScale/gmd:MD_RepresentativeFraction',
        'xpath_property': './gmd:denominator',
        'xpath_extract': './gco:Integer/text()',
        'xpath_extract_fn': lambda l: int(l[0]) if l else None,
        'adjust_property_element': common_util.adjust_integer,
    },
    'language': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification',
        'xpath_property': './gmd:language',
        'xpath_extract': './gmd:LanguageCode/@codeListValue',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': common_util.adjust_language,
    },
    'extent': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:extent/gmd:EX_Extent',
        'xpath_property': './gmd:geographicElement[gmd:EX_GeographicBoundingBox]',
        'xpath_extract': './gmd:EX_GeographicBoundingBox/*/gco:Decimal/text()',
        'xpath_extract_fn': lambda l: [float(l[0]), float(l[2]), float(l[1]), float(l[3])] if len(l) == 4 else None,
        'adjust_property_element': common_util.adjust_extent,
    },
    'wms_url': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:distributionInfo/gmd:MD_Distribution/gmd:transferOptions/gmd:MD_DigitalTransferOptions',
        'xpath_property': f'./gmd:onLine[gmd:CI_OnlineResource/gmd:protocol/gmx:Anchor/@xlink:href="https://services.cuzk.cz/registry/codelist/OnlineResourceProtocolValue/OGC:WMS-{wms.VERSION}-http-get-capabilities"]',
        'xpath_extract': './gmd:CI_OnlineResource/gmd:linkage/gmd:URL/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': partial(common_util.adjust_online_url,
                                           resource_protocol=f'OGC:WMS-{wms.VERSION}-http-get-capabilities',
                                           online_function='download'),
    },
    'wfs_url': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:distributionInfo/gmd:MD_Distribution/gmd:transferOptions/gmd:MD_DigitalTransferOptions',
        'xpath_property': f'./gmd:onLine[gmd:CI_OnlineResource/gmd:protocol/gmx:Anchor/@xlink:href="https://services.cuzk.cz/registry/codelist/OnlineResourceProtocolValue/OGC:WFS-{wfs.VERSION}-http-get-capabilities"]',
        'xpath_extract': './gmd:CI_OnlineResource/gmd:linkage/gmd:URL/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': partial(common_util.adjust_online_url,
                                           resource_protocol=f'OGC:WFS-{wfs.VERSION}-http-get-capabilities',
                                           online_function='download'),
    },
    'layer_endpoint': {
        'xpath_parent': '/gmd:MD_Metadata/gmd:distributionInfo/gmd:MD_Distribution/gmd:transferOptions/gmd:MD_DigitalTransferOptions',
        'xpath_property': './gmd:onLine[gmd:CI_OnlineResource/gmd:protocol/gmx:Anchor/@xlink:href="https://services.cuzk.cz/registry/codelist/OnlineResourceProtocolValue/WWW:LINK-1.0-http--link"]',
        'xpath_extract': './gmd:CI_OnlineResource/gmd:linkage/gmd:URL/text()',
        'xpath_extract_fn': lambda l: l[0] if l else None,
        'adjust_property_element': partial(common_util.adjust_online_url, resource_protocol='WWW:LINK-1.0-http--link',
                                           online_function='information'),
    },
}


def get_metadata_comparison(workspace, layername):
    uuid = get_layer_uuid(workspace, layername)
    csw = common_util.create_csw()
    if uuid is None or csw is None:
        return {}
    muuid = get_metadata_uuid(uuid)
    el = common_util.get_record_element_by_id(csw, muuid)
    if el is None:
        return {}

    # current_app.logger.info(f"xml\n{ET.tostring(el)}")

    props = common_util.parse_md_properties(el, [
        'abstract',
        'extent',
        'graphic_url',
        'identifier',
        'layer_endpoint',
        'language',
        'organisation_name',
        'publication_date',
        'revision_date',
        'reference_system',
        'scale_denominator',
        'title',
        'wfs_url',
        'wms_url',
    ], METADATA_PROPERTIES)
    # current_app.logger.info(f"props:\n{json.dumps(props, indent=2)}")
    # current_app.logger.info(f"csw.request={csw.request}")
    url = csw.request.replace(settings.CSW_URL, settings.CSW_PROXY_URL)
    return {
        f"{url}": props
    }
