# Metadata

Layman is able to publish partial metadata records to [OGC Catalogue Service](https://www.opengeospatial.org/standards/cat) [Micka](http://micka.bnhelp.cz/). Records are partial because Layman does not know all metadata properties. Below are listed
- [metadata properties that are known to Layman](#metadata-properties-known-to-layman) 
- [metadata properties guessable by Layman](#metadata-properties-guessable-by-layman) (not yet implemented) 
- [metadata properties unknown to Layman](#metadata-properties-unknown-to-layman), that Layman is aware of. 

Although metadata records sent to Micka are partial, they can (and should) be completed using Micka web editor GUI. URL of layer's metadata record leading to Micka's GUI is available in [GET Layer](rest.md#get-layer) response as `metadata.record_url` property. To complete metadata records, just open this URL in browser, log in to micka as editor or admin, and complete the record.

Properties listed below contains
- unique name (as heading)
- multiplicity of the property (usually 1 or 1..*)
- shape (type) of the property value
- example of the property value
- XPath expressions pointing to specific placement of the property inside metadata document 

On POST requests, Layman automatically creates metadata record using CSW with values of all known and guessable properties. On PATCH requests, Layman also automatically updates metadata record, but only for these metadata properties, whose values were `equal_or_none` in Metadata Comparison response at the time just when PATCH started.


## Metadata properties known to Layman

### abstract
Multiplicity: 1

Shape: String

Example: `"Klasifikace pokryvu zemského povrchu v rozsahu ČR."`

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:abstract/gco:CharacterString/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/gmd:abstract/gco:CharacterString/text()`


### extent
Multiplicity: 1

Shape: Array of four numbers `[min latitude, min longitude, max latitude, max longitude]`

Example: `[11.87, 48.12, 19.13, 51.59]`

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:extent/gmd:EX_Extent/gmd:geographicElement[gmd:EX_GeographicBoundingBox]/gmd:EX_GeographicBoundingBox/*/gco:Decimal/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/srv:extent/gmd:EX_Extent/gmd:geographicElement[gmd:EX_GeographicBoundingBox]/gmd:EX_GeographicBoundingBox/*/gco:Decimal/text()`


### graphic_url
Multiplicity: 1

Shape: String

Example: `"http://layman_test_run_1:8000/rest/testuser1/layers/ne_110m_admin_0_countries_shp/thumbnail"`

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:graphicOverview[gmd:MD_BrowseGraphic/gmd:fileName/gco:CharacterString]/gmd:MD_BrowseGraphic/gmd:fileName/gco:CharacterString/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/gmd:graphicOverview[gmd:MD_BrowseGraphic/gmd:fileName/gco:CharacterString]/gmd:MD_BrowseGraphic/gmd:fileName/gco:CharacterString/text()`


### identifier
Multiplicity: 1

Shape: Object with keys and values:
- **identifier**: String. Identifier itself.
- **label**: String. Identifier label.

Example: 
```
{
    "identifier": "http://layman_test_run_1:8000/rest/testuser1/layers/ne_110m_admin_0_countries_shp",
    "label": "ne_110m_admin_0_countries_shp"
}
```

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation/gmd:identifier/gmd:MD_Identifier/gmd:code/gmx:Anchor/@xlink:href`

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/gmd:citation/gmd:CI_Citation/gmd:identifier/gmd:MD_Identifier/gmd:code/gmx:Anchor/@xlink:href`


### layer_endpoint
Multiplicity: 1

Shape: String

Example: `"http://layman_test_run_1:8000/rest/testuser1/layers/ne_110m_admin_0_countries_shp"`

XPath for Layer: `/gmd:MD_Metadata/gmd:distributionInfo/gmd:MD_Distribution/gmd:transferOptions/gmd:MD_DigitalTransferOptions/gmd:onLine[gmd:CI_OnlineResource/gmd:protocol/gmx:Anchor/@xlink:href="https://services.cuzk.cz/registry/codelist/OnlineResourceProtocolValue/WWW:LINK-1.0-http--link"]/gmd:CI_OnlineResource/gmd:linkage/gmd:URL/text()`


### map_endpoint
Multiplicity: 1

Shape: String

Example: `"http://layman_test_run_1:8000/rest/testuser1/maps/svet"`

XPath for Map: `/gmd:MD_Metadata/gmd:distributionInfo/gmd:MD_Distribution/gmd:transferOptions/gmd:MD_DigitalTransferOptions/gmd:onLine[gmd:CI_OnlineResource/gmd:protocol/gmx:Anchor/@xlink:href="https://services.cuzk.cz/registry/codelist/OnlineResourceProtocolValue/WWW:LINK-1.0-http--link" and gmd:CI_OnlineResource/gmd:function/gmd:CI_OnLineFunctionCode/@codeListValue="information"]/gmd:CI_OnlineResource/gmd:linkage/gmd:URL/text()`


### map_file_endpoint
Multiplicity: 1

Shape: String

Example: `"http://layman_test_run_1:8000/rest/testuser1/maps/svet/file"`

XPath for Map: `/gmd:MD_Metadata/gmd:distributionInfo/gmd:MD_Distribution/gmd:transferOptions/gmd:MD_DigitalTransferOptions/gmd:onLine[gmd:CI_OnlineResource/gmd:protocol/gmx:Anchor/@xlink:href="https://services.cuzk.cz/registry/codelist/OnlineResourceProtocolValue/WWW:LINK-1.0-http--link" and gmd:CI_OnlineResource/gmd:function/gmd:CI_OnLineFunctionCode/@codeListValue="download"]/gmd:CI_OnlineResource/gmd:linkage/gmd:URL/text()`


### md_date_stamp
Multiplicity: 1

Shape: String

Example: `"2007-05-25"`

XPath for Layer: `/gmd:MD_Metadata/gmd:dateStamp/gco:Date/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:dateStamp/gco:Date/text()`


### md_file_identifier
Multiplicity: 1

Shape: String

Example: `"m-91147a27-1ff4-4242-ba6d-faffb92224c6"`

XPath for Layer: `/gmd:MD_Metadata/gmd:fileIdentifier/gco:CharacterString/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:fileIdentifier/gco:CharacterString/text()`


### operates_on
Multiplicity: 1..*

Shape: Object with keys and values:
- **xlink:href**: String. Link to other metadata record.
- **xlink:title**: String. Reference title.

Example: 
```
{
    "xlink:title": "http://localhost:3080/csw?SERVICE=CSW&amp;VERSION=2.0.2&amp;REQUEST=GetRecordById&amp;OUTPUTSCHEMA=http://www.isotc211.org/2005/gmd&amp;ID=m-39cc8994-adbc-427a-8522-569eb7e691b2#_m-39cc8994-adbc-427a-8522-569eb7e691b2",
    "xlink:href": "hranice"
}
```

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/srv:operatesOn[@xlink:href]/@xlink:href`


### publication_date
Multiplicity: 1

Shape: String

Example: `"2007-05-25"`

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation/gmd:date[gmd:CI_Date/gmd:dateType/gmd:CI_DateTypeCode[@codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" and @codeListValue="publication"]]/gmd:CI_Date/gmd:date/gco:Date/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/gmd:citation/gmd:CI_Citation/gmd:date[gmd:CI_Date/gmd:dateType/gmd:CI_DateTypeCode[@codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" and @codeListValue="publication"]]/gmd:CI_Date/gmd:date/gco:Date/text()`


### reference_system
Multiplicity: 1..*

Shape: Array of integers (EPSG codes).

Example: `[3857, 4326]`

XPath for Layer: `/gmd:MD_Metadata/gmd:referenceSystemInfo[gmd:MD_ReferenceSystem/gmd:referenceSystemIdentifier/gmd:RS_Identifier/gmd:code/gmx:Anchor[starts-with(@xlink:href, "http://www.opengis.net/def/crs/EPSG/0/")]]/gmd:MD_ReferenceSystem/gmd:referenceSystemIdentifier/gmd:RS_Identifier/gmd:code/gmx:Anchor/@xlink:href`

XPath for Map: `/gmd:MD_Metadata/gmd:referenceSystemInfo[gmd:MD_ReferenceSystem/gmd:referenceSystemIdentifier/gmd:RS_Identifier/gmd:code/gmx:Anchor[starts-with(@xlink:href, "http://www.opengis.net/def/crs/EPSG/0/")]]/gmd:MD_ReferenceSystem/gmd:referenceSystemIdentifier/gmd:RS_Identifier/gmd:code/gmx:Anchor/@xlink:href`


### revision_date
Multiplicity: 1

Shape: String

Example: `"2007-05-25"`

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation/gmd:date[gmd:CI_Date/gmd:dateType/gmd:CI_DateTypeCode[@codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" and @codeListValue="revision"]]/gmd:CI_Date/gmd:date/gco:Date/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/gmd:citation/gmd:CI_Citation/gmd:date[gmd:CI_Date/gmd:dateType/gmd:CI_DateTypeCode[@codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" and @codeListValue="revision"]]/gmd:CI_Date/gmd:date/gco:Date/text()`


### title
Multiplicity: 1

Shape: String

Example: `"World Countries"`

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation/gmd:title/gco:CharacterString/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/gmd:citation/gmd:CI_Citation/gmd:title/gco:CharacterString/text()`


### wfs_url
Multiplicity: 1

Shape: String

Example: `"http://localhost:8600/geoserver/testuser1/ows"`

XPath for Layer: `/gmd:MD_Metadata/gmd:distributionInfo/gmd:MD_Distribution/gmd:transferOptions/gmd:MD_DigitalTransferOptions/gmd:onLine[gmd:CI_OnlineResource/gmd:protocol/gmx:Anchor/@xlink:href="https://services.cuzk.cz/registry/codelist/OnlineResourceProtocolValue/OGC:WFS-2.0.0-http-get-capabilities"]/gmd:CI_OnlineResource/gmd:linkage/gmd:URL/text()`


### wms_url
Multiplicity: 1

Shape: String

Example: `"http://localhost:8600/geoserver/testuser1/ows"`

XPath for Layer: `/gmd:MD_Metadata/gmd:distributionInfo/gmd:MD_Distribution/gmd:transferOptions/gmd:MD_DigitalTransferOptions/gmd:onLine[gmd:CI_OnlineResource/gmd:protocol/gmx:Anchor/@xlink:href="https://services.cuzk.cz/registry/codelist/OnlineResourceProtocolValue/OGC:WMS-1.3.0-http-get-capabilities"]/gmd:CI_OnlineResource/gmd:linkage/gmd:URL/text()`


## Metadata properties guessable by Layman

### language
Multiplicity: 1

Shape: String

Example: `"cze"`

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:language/gmd:LanguageCode/@codeListValue`

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/gmd:language/gmd:LanguageCode/@codeListValue`


### scale_denominator
Multiplicity: 1

Shape: Integer

Example: `25000`

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:spatialResolution/gmd:MD_Resolution/gmd:equivalentScale/gmd:MD_RepresentativeFraction/gmd:denominator/gco:Integer/text()`


## Metadata properties unknown to Layman

### md_organisation_name
Multiplicity: 1

Shape: String

Example: `"Ministerstvo životního prostředí ČR"`

XPath for Layer: `/gmd:MD_Metadata/gmd:contact/gmd:CI_ResponsibleParty/gmd:organisationName/gco:CharacterString/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:contact/gmd:CI_ResponsibleParty/gmd:organisationName/gco:CharacterString/text()`


### organisation_name
Multiplicity: 1

Shape: String

Example: `"Ministerstvo životního prostředí ČR"`

XPath for Layer: `/gmd:MD_Metadata/gmd:identificationInfo/gmd:MD_DataIdentification/gmd:pointOfContact/gmd:CI_ResponsibleParty/gmd:organisationName/gco:CharacterString/text()`

XPath for Map: `/gmd:MD_Metadata/gmd:identificationInfo/srv:SV_ServiceIdentification/gmd:pointOfContact/gmd:CI_ResponsibleParty/gmd:organisationName/gco:CharacterString/text()`
