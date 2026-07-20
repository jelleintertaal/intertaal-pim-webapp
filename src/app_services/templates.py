# -*- coding: utf-8 -*-
"""
templates.py — Vaste outputformats voor de twee opzoek-tabs.

De kolomlijsten zijn 1-op-1 gegenereerd uit de aangeleverde templates
(leidend volgens de opdracht):
  - Nielsen : "Nielson gevraagde data.xlsx"           (141 kolommen)
  - CB      : "CB data gewenst 1726_ORIGINEEL_backup.xlsx" (16 kolommen)

LET OP: exact behouden zoals aangeleverd — inclusief 'seriedeel ' met
trailing spatie en de kolomnaam 'EAN / GTIN / SKU / ISBN'.
De app voegt in de output NA deze kolommen 'Status' en 'Bron' toe.
"""

# Kolom 1 = input-ISBN; kolom 2 t/m 141 = Nielsen veldcodes
NIELSEN_ISBN_COL = 'EAN / GTIN / SKU / ISBN'

NIELSEN_COLUMNS = [
    'EAN / GTIN / SKU / ISBN', 'ISBN13', 'ISBN13H', 'EAN', 'FTS', 'LA',
    'TL', 'PVNO1', 'PT1', 'ST', 'YS', 'PUBPD',
    'UKNBDLPD', 'EMBD', 'REISD', 'PUBSC', 'PUBST', 'SN',
    'NWS', 'ISSN', 'CNF1', 'CNI1', 'CNS1', 'CNSI1',
    'CR1', 'CRT1', 'CNF2', 'CNI2', 'CNS2', 'CNSI2',
    'CR2', 'CRT2', 'CNF3', 'CNI3', 'CNS3', 'CNSI3',
    'CR3', 'CRT3', 'HMM', 'WMM', 'SMM', 'WG',
    'EDSL', 'PFC', 'PFCT', 'PFD1', 'PFDT1', 'PFD2',
    'PFDT2', 'PAGNUM', 'NOI', 'ILL', 'CIS', 'IMPN',
    'PUBN', 'COP', 'COM', 'PUBID', 'IMPID', 'SLC',
    'SLT', 'LS', 'LC1', 'LT1', 'TFC1', 'TFT1',
    'NAC1', 'NAT1', 'NAC2', 'NAT2', 'IA', 'RA',
    'KSC', 'KST', 'KEYWORDS', 'THEMASCHV', 'THEMASC1', 'THEMAST1',
    'THEMASC2', 'THEMAST2', 'THEMAQC1', 'THEMAQT1', 'THEMAQC2', 'THEMAQT2',
    'BISACC1', 'BISACT1', 'BISACC2', 'BISACT2', 'BIC2SC1', 'BIC2ST1',
    'PRODCC', 'PRODCT', 'LOCSH1', 'LOCSH2', 'NBDFSD', 'NBDFLD',
    'NBDFBIOG', 'NBDFREV', 'NBDFP', 'NBDFTOC', 'ERSL', 'NERSL',
    'NFSRSL', 'RSS', 'EURCCPRRRP', 'EURCCPRRRPLT', 'EURCCPLCD', 'EURCCPTC',
    'EURCCPTD', 'EURCCPRDC', 'GBPCCPRRRP', 'GBPCCPRRRPLT', 'GBPCCPLCD', 'IMAGFLAG',
    'WF1', 'WFTC1', 'WFTT1', 'WFLTC1', 'WFLTT1', 'RPI1',
    'RPI2', 'RPI3', 'RPI4', 'RPI5', 'RPTT1', 'RPTT2',
    'RPTT3', 'RPTT4', 'RPTT5', 'EURNBDPAC', 'EURNBDPAT', 'EURNBDEAD',
    'EURNBDPASLCD', 'UKNBDPAC', 'UKNBDPAT', 'UKNBDEAD', 'UKNBDPASLCD', 'USNBDPAC',
    'USNBDPAT', 'USNBDEAD', 'USNBDPASLCD',
]

# De 140 op te halen Nielsen-velden (alles behalve de ISBN-kolom)
NIELSEN_DATA_COLUMNS = [c for c in NIELSEN_COLUMNS if c != NIELSEN_ISBN_COL]

CB_ISBN_COL = 'Isbn'

# Alle 50 kolommen zoals aangeleverd in "CB nieuwe uitvraag_FILLED (1).xlsx":
# kolom 1 (Isbn) = input-sleutel, 2 t/m 49 = rauwe CB Algolia velden,
# 50 (ImageUrl_nieuw) = door onze webapp toegevoegde mind-books URL
# (grote cover, i.p.v. de CB thumbnail).
CB_COLUMNS = [
    'Isbn',
    'objectID', 'LastUpdateDTD',
    'Hoofdtitel', 'Ondertitel', 'Deeltitel', 'Sectietitel', 'OrigineleTitel',
    'Auteur', 'EersteBetrokkene', 'Redacteur', 'Vertaler', 'Bewerker',
    'Illustrator', 'Fotograaf', 'Corporatie',
    'Uitgever', 'Imprint', 'Verschijningsvorm', 'Taal', 'Boeksoort',
    'Verschijningsdatum', 'Verschijningsjaar', 'VerwachteVerschijningsdatum',
    'SpecialeUitgaveInd', 'ReeksNm', 'ReeksNr', 'Prijs',
    'Nur', 'NurNivo1', 'NurNivo2', 'NurNivo3',
    'ThemaHoofdSubject', 'ThemaSubjects', 'ThemaExtraSubjects',
    'ThemaQualifiersPedagogischDoel', 'ThemaQualifiersTaal',
    'ThemaQualifiersDoelgroep', 'ThemaQualifiersPlaats',
    'ThemaQualifiersTijdperk', 'ThemaQualifiersStijl',
    'BeschikbaarheidsCode', 'bestelbaar_nl', 'bestelbaar_be', 'is_bestelbaar',
    'assortiment_type_nl', 'assortiment_type_be', 'VerkooplandUitsluiting',
    'ImageUrl', 'ImageUrl_nieuw',
]

STATUS_COL = "Status"
BRON_COL = "Bron"
