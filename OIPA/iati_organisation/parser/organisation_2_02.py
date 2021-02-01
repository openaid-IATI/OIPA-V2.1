import logging

from django.conf import settings

from geodata.models import Country, Region
from iati.parser.exceptions import (
    FieldValidationError, ParserError, RequiredFieldError
)
from iati.parser.iati_parser import IatiParser
from iati_codelists import models as codelist_models
from iati_organisation.models import (
    DocumentLinkRecipientCountry, DocumentLinkTitle, Organisation,
    OrganisationDocumentLink, OrganisationDocumentLinkCategory,
    OrganisationDocumentLinkLanguage, OrganisationName, OrganisationNarrative,
    OrganisationReportingOrganisation, RecipientCountryBudget,
    RecipientCountryBudgetLine, RecipientOrgBudget, RecipientOrgBudgetLine,
    RecipientRegionBudget, RecipientRegionBudgetLine, TotalBudget,
    TotalBudgetLine, TotalExpenditure, TotalExpenditureLine
)
from iati_organisation.parser import post_save
from iati_vocabulary.models import RegionVocabulary
from solr.organisation.tasks import OrganisationTaskIndexing

# Get an instance of a logger
logger = logging.getLogger(__name__)


class Parse(IatiParser):
    """
    # NOTE: This parsed version is only covered the DataSet Organisation file
    as the following:
    - Total Budget
    -- Total Budget Line
    - Total Expenditure
    -- Total Expenditure Line
    - Organisation Document Link

    # TODO: Cover others element as The IATI Organisation File Standard
    http://reference.iatistandard.org/202/organisation-standard/overview/organisation-file/
    """

    organisation_identifier = ''

    def __init__(self, *args, **kwargs):
        super(Parse, self).__init__(*args, **kwargs)
        self.VERSION = '2.02'

        # default currency
        self.default_currency = None

        # We need a current index to put the current model
        # on the process parse
        self.organisation_document_link_current_index = 0
        self.document_link_title_current_index = 0
        self.document_link_language_current_index = 0
        self.total_budget_current_index = 0
        self.total_budget_line_current_index = 0
        self.total_expenditure_current_index = 0
        self.total_expenditure_line_current_index = 0

    def add_narrative(self, element, parent):
        default_lang = self.default_lang  # set on activity (if set)
        lang = element.attrib.get('{http://www.w3.org/XML/1998/namespace}lang')
        text = element.text

        language = self.get_or_none(codelist_models.Language, code=lang)

        if not language:
            language = default_lang

        if not parent:
            raise ParserError(
                "Unknown",
                "Narrative",
                "parent object must be passed")

        register_name = parent.__class__.__name__ + "Narrative"

        if not language:
            raise RequiredFieldError(
                register_name,
                "xml:lang",
                "must specify xml:lang on iati-activity or xml:lang on \
                        the element itself")
        if not text:
            raise RequiredFieldError(
                register_name,
                "text",
                "empty narrative")

        narrative = OrganisationNarrative()
        narrative.language = language
        narrative.content = element.text
        # This (instead of narrative.related_object) is required, otherwise
        # related object doesn't get passed to the model_store (memory) and
        # 'update_related()' fails.
        # It should probably be passed to the __init__() ?
        setattr(narrative, '_related_object', parent)

        narrative.organisation = self.get_model('Organisation')

        # TODO: handle this differently (also: breaks tests)
        self.register_model(register_name, narrative)

    def _get_currency_or_raise(self, model_name, currency):
        """
        get default currency if not available for currency-related fields
        """
        if not currency:
            currency = getattr(self.get_model(
                'Organisation'), 'default_currency')
            if not currency:
                raise RequiredFieldError(
                    model_name,
                    "currency",
                    "must specify default-currency on iati-organisation or \
                        as currency on the element itself")

        return currency

    def iati_organisations__iati_organisation(self, element):
        id = element.xpath('organisation-identifier/text()')[0]
        normalized_id = self._normalize(id)
        last_updated_datetime = self.validate_date(
            element.attrib.get('last-updated-datetime'))
        # default is here to make it default to settings 'DEFAULT_LANG' on no
        # language set (validation error we want to be flexible per instance)

        default_lang_code = element.attrib.get(
            '{http://www.w3.org/XML/1998/namespace}lang',
            settings.DEFAULT_LANG)
        if default_lang_code:
            default_lang_code = default_lang_code.lower()

        default_lang = self.get_or_none(
            codelist_models.Language,
            code=default_lang_code
        )

        default_currency = self.get_or_none(
            codelist_models.Currency,
            code=element.attrib.get('default-currency'))

        if not id:
            raise RequiredFieldError(
                "",
                "id",
                "organisation: must contain organisation-identifier")

        # TODO: check for last-updated-datetime - 2017-03-27
        old_organisation = self.get_or_none(
            Organisation, organisation_identifier=id)

        if old_organisation:
            OrganisationName.objects.filter(
                organisation=old_organisation).delete()
            OrganisationReportingOrganisation.objects.filter(
                organisation=old_organisation).delete()
            TotalBudget.objects.filter(
                organisation=old_organisation).delete()
            RecipientOrgBudget.objects.filter(
                organisation=old_organisation).delete()
            RecipientCountryBudget.objects.filter(
                organisation=old_organisation).delete()
            RecipientRegionBudget.objects.filter(
                organisation=old_organisation).delete()
            TotalExpenditure.objects.filter(
                organisation=old_organisation).delete()
            OrganisationDocumentLink.objects.filter(
                organisation=old_organisation).delete()

            organisation = old_organisation
        else:
            organisation = Organisation()

        organisation.organisation_identifier = id
        organisation.normalized_organisation_identifier = normalized_id
        organisation.last_updated_datetime = last_updated_datetime
        organisation.default_lang = default_lang
        organisation.iati_standard_version_id = self.VERSION
        organisation.default_currency = default_currency

        organisation.published = True
        organisation.ready_to_publish = True
        organisation.modified = False
        organisation.dataset = self.dataset

        self.organisation_identifier = organisation.organisation_identifier
        self.default_currency = default_currency

        # for later reference
        self.default_lang = default_lang

        self.register_model('Organisation', organisation)

        return element

    def iati_organisations__iati_organisation__organisation_identifier(
            self, element):
        # already set in iati_organisation
        return element

    def iati_organisations__iati_organisation__name(self, element):
        name_list = self.get_model_list('OrganisationName')

        if name_list and len(name_list) > 0:
            raise FieldValidationError(
                "name", "Duplicate names are not allowed")

        organisation = self.get_model('Organisation')

        name = OrganisationName()
        name.organisation = organisation

        self.register_model('OrganisationName', name)

        return element

    def iati_organisations__iati_organisation__name__narrative(self, element):
        model = self.get_model('OrganisationName')
        self.add_narrative(element, model)

        if element.text:

            organisation = self.get_model('Organisation')

            if organisation.primary_name:
                default_lang = self.default_lang  # set on activity (if set)
                lang = element.attrib.get(
                    '{http://www.w3.org/XML/1998/namespace}lang', default_lang)
                if lang == 'en':
                    organisation.primary_name = element.text
            else:
                organisation.primary_name = element.text
        return element

    def iati_organisations__iati_organisation__reporting_org(self, element):
        # Although OrganisationReportingOrganisation and Organisation has
        # One-to-One relation on the database level, we check here whether
        # element 'reporting-org' occurs only once in the parent element
        # 'organisation'.
        organisation = self.get_model('Organisation')
        if 'OrganisationReportingOrganisation' in self.model_store:
            for reporting_org in self.model_store[
                    'OrganisationReportingOrganisation']:
                if reporting_org.organisation == organisation:
                    raise ParserError("Organisation",
                                      "OrganisationReportingOrganisation",
                                      "must occur no more than once.")
        # narrative is parsed in different method but as it is required
        # sub-element in 'name' element so we check it here.
        narrative = element.xpath("narrative")
        if len(narrative) < 1:
            raise RequiredFieldError("OrganisationName", "narrative",
                                     "must occur at least once.")
        reporting_org_identifier = element.attrib.get("ref")
        if reporting_org_identifier is None:
            raise RequiredFieldError("OrganisationReportingOrganisation",
                                     "ref", "required field missing.")
        org_type = element.attrib.get("type")
        if org_type is None:
            raise RequiredFieldError("OrganisationReportingOrganisation",
                                     "type", "required field missing.")
        # here org_type is OrganisationType object.
        org_type = self.get_or_none(codelist_models.OrganisationType,
                                    code=org_type)
        if org_type is None:
            raise FieldValidationError(
                "OrganisationReportingOrganisation",
                "type",
                "not found on the accompanying codelist.",
                None,
                None,
            )
        secondary_reporter = self.makeBool(element.attrib.get(
            "secondary-reporter"))

        reporting_org = OrganisationReportingOrganisation()
        reporting_org.organisation = organisation
        reporting_org.org_type = org_type
        reporting_org.secondary_reporter = secondary_reporter
        reporting_org.reporting_org_identifier = reporting_org_identifier

        self.register_model("OrganisationReportingOrganisation", reporting_org)
        return element

    def iati_organisations__iati_organisation__reporting_org__narrative(
            self, element):
        """atributes:

        tag:narrative"""
        model = self.get_model('OrganisationReportingOrganisation')
        self.add_narrative(element, model)
        return element

    def iati_organisations__iati_organisation__total_budget(self, element):
        """atributes:

        tag:total-budget"""
        status = self.get_or_none(
            codelist_models.BudgetStatus, code=element.attrib.get('status'))

        model = self.get_model('Organisation')
        total_budget = TotalBudget()
        total_budget.organisation = model

        if status:
            total_budget.status = status

        self.total_budget_current_index = \
            self.register_model('TotalBudget', total_budget)

        # store element
        return element

    def iati_organisations__iati_organisation__total_budget__period_start(
            self, element):
        """atributes:
        iso-date:2014-01-01

        tag:period-start"""
        model = self.get_model('TotalBudget', self.total_budget_current_index)
        model.period_start = self.validate_date(element.attrib.get('iso-date'))

        # store element
        return element

    def iati_organisations__iati_organisation__total_budget__period_end(
            self, element):
        """atributes:
        iso-date:2014-12-31

        tag:period-end"""
        model = self.get_model('TotalBudget', self.total_budget_current_index)
        model.period_end = self.validate_date(element.attrib.get('iso-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__total_budget__value(
            self, element):
        """atributes:
        currency:USD
        value-date:2014-01-0

        tag:value"""
        model = self.get_model('TotalBudget', self.total_budget_current_index)
        model.currency = self.get_or_none(
            codelist_models.Currency,
            code=self._get_currency_or_raise(
                'total-budget/value',
                element.attrib.get('currency')))
        model.value_date = self.validate_date(element.attrib.get('value-date'))
        model.value = element.text
        # store element
        return element

    def iati_organisations__iati_organisation__total_budget__budget_line(
            self, element):
        """atributes:
        ref:1234

        tag:budget-line"""
        budget_line = TotalBudgetLine()
        budget_line.ref = element.attrib.get('ref', '-')

        budget_line.total_budget = self.get_model(
            'TotalBudget', self.total_budget_current_index)

        self.total_budget_line_current_index = \
            self.register_model('TotalBudgetLine', budget_line)
        # store element
        return element

    def iati_organisations__iati_organisation__total_budget__budget_line__value(self, element):  # NOQA: E501
        """atributes:
        currency:USD
        value-date:2014-01-01

        tag:value"""
        model = self.get_model('TotalBudgetLine',
                               self.total_budget_line_current_index)

        model.currency = self.get_or_none(
            codelist_models.Currency,
            code=self._get_currency_or_raise(
                'total-budget/budget-line/value',
                element.attrib.get('currency')))
        model.value = element.text
        model.value_date = self.validate_date(element.attrib.get('value-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__total_budget__budget_line__narrative(self, element):  # NOQA: E501
        """atributes:

        tag:narrative"""
        model = self.get_model('TotalBudgetLine',
                               self.total_budget_line_current_index)

        self.add_narrative(element, model)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_org_budget(
            self, element):
        """atributes:

        tag:recipient-org-budget"""
        status = self.get_or_none(
            codelist_models.BudgetStatus, code=element.attrib.get('status'))

        model = self.get_model('Organisation')
        recipient_org_budget = RecipientOrgBudget()
        recipient_org_budget.organisation = model
        if status:
            recipient_org_budget.status = status
        self.register_model('RecipientOrgBudget', recipient_org_budget)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_org_budget__recipient_org(self, element):  # NOQA: E501
        """atributes:
        ref:AA-ABC-1234567

        tag:recipient-org"""
        model = self.get_model('RecipientOrgBudget')
        model.recipient_org_identifier = element.attrib.get('ref')
        if Organisation.objects.filter(
            organisation_identifier=element.attrib.get('ref')
        ).exists():
            model.recipient_org = Organisation.objects.get(
                pk=element.attrib.get('ref'))

        # store element
        return element

    def iati_organisations__iati_organisation__recipient_org_budget__recipient_org__narrative(  # NOQA: E501
            self, element):
        """atributes:

        tag:narrative"""
        model = self.get_model('RecipientOrgBudget')
        self.add_narrative(element, model)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_org_budget__period_start(self, element):  # NOQA: E501
        """atributes:
        iso-date:2014-01-01

        tag:period-start"""
        model = self.get_model('RecipientOrgBudget')
        model.period_start = self.validate_date(element.attrib.get('iso-date'))

        # store element
        return element

    def iati_organisations__iati_organisation__recipient_org_budget__period_end(self, element):  # NOQA: E501
        """atributes:
        iso-date:2014-12-31

        tag:period-end"""
        model = self.get_model('RecipientOrgBudget')
        model.period_end = self.validate_date(element.attrib.get('iso-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_org_budget__value(
            self, element):
        """atributes:
        currency:USD
        value-date:2014-01-01

        tag:value"""
        model = self.get_model('RecipientOrgBudget')
        model.currency = self.get_or_none(
            codelist_models.Currency,
            code=self._get_currency_or_raise(
                'recipient-org-budget/value',
                element.attrib.get('currency')))
        value_date = element.attrib.get('value-date')
        if value_date is None:
            raise RequiredFieldError("RecipientOrgBudget", "value-date",
                                     "required field missing.")
        value_date = self.validate_date(value_date)
        if not value_date:
            raise FieldValidationError(
                "RecipientOrgBudget",
                "value-date",
                "not in the correct range.",
                None,
                None,
            )
        model.value_date = value_date
        model.value = element.text
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_org_budget__budget_line(self, element):  # NOQA: E501
        """atributes:
        ref:1234

        tag:budget-line"""
        org_budget = self.get_model('RecipientOrgBudget')
        budget_line = RecipientOrgBudgetLine()
        budget_line.ref = element.attrib.get('ref')
        budget_line.recipient_org_budget = org_budget
        self.register_model('RecipientOrgBudgetLine', budget_line)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_org_budget__budget_line__value(  # NOQA: E501
            self, element):
        """atributes:
        currency:USD
        value-date:2014-01-01

        tag:value"""
        model = self.get_model('RecipientOrgBudgetLine')
        model.currency = self.get_or_none(
            codelist_models.Currency,
            code=self._get_currency_or_raise(
                'recipient-org-budget/budget-line/value',
                element.attrib.get('currency')))
        model.value = element.text
        model.value_date = self.validate_date(element.attrib.get('value-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_org_budget__budget_line__narrative(  # NOQA: E501
            self, element):
        """atributes:

        tag:narrative"""
        model = self.get_model('RecipientOrgBudgetLine')
        self.add_narrative(element, model)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_country_budget(
            self, element):
        """atributes:

        tag:recipient-country-budget"""
        status = self.get_or_none(
            codelist_models.BudgetStatus, code=element.attrib.get('status'))
        model = self.get_model('Organisation')
        recipient_country_budget = RecipientCountryBudget()
        recipient_country_budget.organisation = model
        if status:
            recipient_country_budget.status = status
        self.register_model('RecipientCountryBudget', recipient_country_budget)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_country_budget__recipient_country(  # NOQA: E501
            self, element):
        """atributes:
        code:AF

        tag:recipient-country"""
        model = self.get_model('RecipientCountryBudget')
        model.country = self.get_or_none(
            Country, code=element.attrib.get('code'))

        # store element
        return element

    def iati_organisations__iati_organisation__recipient_country_budget__recipient_country__narrative(self, element):  # NOQA: E501
        recipient_country_budget = self.get_model(
            'RecipientCountryBudget'
        )
        self.add_narrative(element, recipient_country_budget)

        return element

    def iati_organisations__iati_organisation__recipient_country_budget__period_start(  # NOQA: E501
            self, element):
        """atributes:
        iso-date:2014-01-01

        tag:period-start"""
        model = self.get_model('RecipientCountryBudget')
        model.period_start = self.validate_date(element.attrib.get('iso-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_country_budget__period_end(self, element):  # NOQA: E501
        """atributes:
        iso-date:2014-12-31

        tag:period-end"""
        model = self.get_model('RecipientCountryBudget')
        model.period_end = self.validate_date(element.attrib.get('iso-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_country_budget__value(
            self, element):
        """atributes:
        currency:USD
        value-date:2014-01-01

        tag:value"""
        model = self.get_model('RecipientCountryBudget')
        model.currency = self.get_or_none(
            codelist_models.Currency,
            code=self._get_currency_or_raise(
                'recipient-country-budget/value',
                element.attrib.get('currency')))

        value_date = element.attrib.get("value-date")
        if value_date is None:
            raise RequiredFieldError(
                "RecipientCountryBudget",
                "value-date",
                "required field missing."
            )

        value_date = self.validate_date(value_date)
        if not value_date:
            raise FieldValidationError(
                "RecipientCountryBudget",
                "value-date",
                "not in the correct range.",
                None,
                None,
            )

        model.value = element.text
        model.value_date = value_date
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_country_budget__budget_line(  # NOQA: E501
            self, element):
        """atributes:
        ref:1234

        tag:budget-line"""
        recipient_country_budget = self.get_model('RecipientCountryBudget')
        budget_line = RecipientCountryBudgetLine()
        budget_line.ref = element.attrib.get('ref', '-')
        budget_line.recipient_country_budget = recipient_country_budget
        self.register_model('RecipientCountryBudgetLine', budget_line)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_country_budget__budget_line__value(  # NOQA: E501
            self, element):
        """atributes:
        currency:USD
        value-date:2014-01-01

        tag:value"""
        model = self.get_model('RecipientCountryBudgetLine')
        model.currency = self.get_or_none(
            codelist_models.Currency,
            code=self._get_currency_or_raise(
                'recipient-country-budget/budget-line/value',
                element.attrib.get('currency')))
        model.value = element.text
        model.value_date = self.validate_date(element.attrib.get('value-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_country_budget__budget_line__narrative(  # NOQA: E501
            self, element):
        """atributes:

        tag:narrative"""
        model = self.get_model('RecipientCountryBudgetLine')
        self.add_narrative(element, model)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_region_budget(
            self, element):
        """atributes:

        tag:recipient-region-budget"""
        status = self.get_or_none(
            codelist_models.BudgetStatus, code=element.attrib.get('status'))
        model = self.get_model('Organisation')
        recipient_region_budget = RecipientRegionBudget()
        recipient_region_budget.organisation = model
        if status:
            recipient_region_budget.status = status
        self.register_model('RecipientRegionBudget', recipient_region_budget)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_region_budget__recipient_region(  # NOQA: E501
            self, element):
        """atributes:
        code:AF

        tag:recipient-region"""
        model = self.get_model('RecipientRegionBudget')

        # TODO: make defaults more transparant, here: 'OECD-DAC default'
        vocabulary = self.get_or_none(
            RegionVocabulary, code=element.attrib.get('vocabulary', '1'))
        vocabulary_uri = element.attrib.get('vocabulary-uri')

        model.region = Region.objects.filter(code=element.attrib.get(
            'code'), region_vocabulary=vocabulary).first()

        if not vocabulary:
            raise RequiredFieldError(
                "recipient-region-budget",
                "recipient-region",
                "invalid vocabulary")

        model.vocabulary = vocabulary
        model.vocabulary_uri = vocabulary_uri

        # store element
        return element

    def iati_organistions__iati_organisation__recipient_region_budget__recipient_region__narrative(self, element):  # NOQA: E501
        recipient_region_budget = self.get_model('RecipientRegionBudget')
        self.add_narrative(element, recipient_region_budget)
        return element

    def iati_organisations__iati_organisation__recipient_region_budget__period_start(  # NOQA: E501
            self, element):
        """atributes:
        iso-date:2014-01-01

        tag:period-start"""
        model = self.get_model('RecipientRegionBudget')
        model.period_start = self.validate_date(element.attrib.get('iso-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_region_budget__period_end(self, element):  # NOQA: E501
        """atributes:
        iso-date:2014-12-31

        tag:period-end"""
        model = self.get_model('RecipientRegionBudget')
        model.period_end = self.validate_date(element.attrib.get('iso-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_region_budget__value(
            self, element):
        """atributes:
        currency:USD
        value-date:2014-01-01

        tag:value"""
        model = self.get_model('RecipientRegionBudget')
        model.currency = self.get_or_none(
            codelist_models.Currency,
            code=self._get_currency_or_raise(
                'recipient-region-budget/value',
                element.attrib.get('currency')))
        value_date = element.attrib.get('value-date')
        if value_date is None:
            raise RequiredFieldError(
                "RecipientRegionBudget",
                "value-date",
                "required field missing."
            )
        value_date = self.validate_date(value_date)
        if not value_date:
            raise FieldValidationError(
                "RecipientRegionBudget",
                "value-date",
                "not in the correct range.",
                None,
                None,
            )
        model.value = element.text
        model.value_date = value_date
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_region_budget__budget_line(self, element):  # NOQA: E501
        """atributes:
        ref:1234

        tag:budget-line"""
        recipient_region_budget = self.get_model('RecipientRegionBudget')
        budget_line = RecipientRegionBudgetLine()
        budget_line.ref = element.attrib.get('ref')
        budget_line.recipient_region_budget = recipient_region_budget
        self.register_model('RecipientRegionBudgetLine', budget_line)
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_region_budget__budget_line__value(  # NOQA: E501
            self, element):
        """atributes:
        currency:USD
        value-date:2014-01-01

        tag:value"""
        model = self.get_model('RecipientRegionBudgetLine')
        model.currency = self.get_or_none(
            codelist_models.Currency,
            code=self._get_currency_or_raise(
                'recipient-region-budget/budget-line/value',
                element.attrib.get('currency')))
        model.value = element.text
        model.value_date = self.validate_date(element.attrib.get('value-date'))
        # store element
        return element

    def iati_organisations__iati_organisation__recipient_region_budget__budget_line__narrative(  # NOQA: E501
            self, element):
        """atributes:

        tag:narrative"""
        model = self.get_model('RecipientRegionBudgetLine')
        self.add_narrative(element, model)
        # store element
        return element

    def iati_organisations__iati_organisation__total_expenditure(
            self, element):
        """
        """
        model = self.get_model('Organisation')
        total_expenditure = TotalExpenditure()
        total_expenditure.organisation = model

        self.total_expenditure_current_index = \
            self.register_model('TotalExpenditure', total_expenditure)

        return element

    def iati_organisations__iati_organisation__total_expenditure__period_start(
            self, element):
        """
        """
        model = self.get_model(
            'TotalExpenditure', self.total_expenditure_current_index)
        model.period_start = self.validate_date(element.attrib.get('iso-date'))
        return element

    def iati_organisations__iati_organisation__total_expenditure__period_end(
            self, element):
        """
        """
        model = self.get_model(
            'TotalExpenditure', self.total_expenditure_current_index)
        model.period_end = self.validate_date(element.attrib.get('iso-date'))
        return element

    def iati_organisations__iati_organisation__total_expenditure__value(
            self, element):
        """
        """
        model = self.get_model(
            'TotalExpenditure', self.total_expenditure_current_index)
        code = element.attrib.get('currency')
        currency = self.get_or_none(codelist_models.Currency, code=code)

        if not code:
            raise RequiredFieldError(
                "total-expenditure/value/currency",
                "code",
                "required element empty")

        if not currency:
            raise FieldValidationError(
                "total-expenditure/value/currency",
                "code",
                "not found on the accompanying code list")

        model.value_date = self.validate_date(element.attrib.get('value-date'))
        model.currency = currency
        model.value = element.text
        return element

    def iati_organisations__iati_organisation__total_expenditure__expense_line(
            self, element):
        """
        """
        budget_line = TotalExpenditureLine()
        budget_line.ref = element.attrib.get('ref', '')
        budget_line.total_expenditure = \
            self.get_model(
                'TotalExpenditure', self.total_expenditure_current_index)

        self.total_expenditure_line_current_index = \
            self.register_model('TotalExpenditureBudgetLine', budget_line)

        return element

    def iati_organisations__iati_organisation__total_expenditure__expense_line__value(  # NOQA: E501
            self, element):
        """
        """
        model = self.get_model('TotalExpenditureBudgetLine',
                               self.total_expenditure_line_current_index)

        currency = element.attrib.get("currency")
        if not currency:
            currency = getattr(
                self.get_model("Organisation"),
                "default_currency"
            )
            if not currency:
                raise RequiredFieldError(
                    "TotalExpenditureLine",
                    "currency",
                    "must specify default-currency on iati-activity or as "
                    "currency on the element itself."
                )

        else:
            currency = self.get_or_none(
                codelist_models.Currency,
                code=currency
            )
            if currency is None:
                raise FieldValidationError(
                    "TotalExpenditureLine",
                    "currency",
                    "not found on the accompanying codelist.",
                    None,
                    None,
                )
        model.value_date = self.validate_date(element.attrib.get('value-date'))
        model.currency = currency
        model.value = element.text
        return element

    def iati_organisations__iati_organisation__total_expenditure__expense_line__narrative(  # NOQA: E501
            self, element):
        """
        """
        model = self.get_model('TotalExpenditureBudgetLine',
                               self.total_expenditure_line_current_index)

        self.add_narrative(element, model)
        return element

    def iati_organisations__iati_organisation__document_link(self, element):
        """atributes:
        format:application/vnd.oasis.opendocument.text
        url:http:www.example.org/docs/report_en.odt

        tag:document-link"""
        model = self.get_model('Organisation')
        document_link = OrganisationDocumentLink()
        document_link.organisation = model
        document_link.url = element.attrib.get('url')
        document_link.file_format = self.get_or_none(
            codelist_models.FileFormat, code=element.attrib.get('format'))

        # Set the document link on the process
        self.organisation_document_link_current_index = \
            self.register_model('OrganisationDocumentLink', document_link)

        # store element
        return element

    def iati_organisations__iati_organisation__document_link__title(
            self, element):
        """atributes:

        tag:title"""

        document_link_title = DocumentLinkTitle()
        self.document_link_title_current_index = \
            self.register_model('DocumentLinkTitle', document_link_title)

        model = self.get_model('OrganisationDocumentLink',
                               self.organisation_document_link_current_index)
        document_link_title.document_link = model

        # store element
        return element

    def iati_organisations__iati_organisation__document_link__title__narrative(
            self, element):
        """atributes:

    tag:narrative"""
        model = self.get_model('DocumentLinkTitle',
                               self.document_link_title_current_index)

        self.add_narrative(element, model)
        # store element
        return element

    def iati_organisations__iati_organisation__document_link__category(
            self, element):
        """atributes:
        code:B01

        tag:category"""
        model = self.get_model('OrganisationDocumentLink',
                               self.organisation_document_link_current_index)

        document_category = self.get_or_none(
            codelist_models.DocumentCategory,
            code=element.attrib.get('code'))

        document_link_category = OrganisationDocumentLinkCategory()
        document_link_category.category = document_category
        document_link_category.document_link = model

        self.register_model(
            'OrganisationDocumentLinkCategory', document_link_category)

        return element

    def iati_organisations__iati_organisation__document_link__language(
            self, element):
        """atributes:
        code:en

        tag:language"""
        organisation_document_link_language = \
            OrganisationDocumentLinkLanguage()

        organisation_document_link_language.language = self.get_or_none(
            codelist_models.Language,
            code=element.attrib.get('code'))

        model = self.get_model('OrganisationDocumentLink',
                               self.organisation_document_link_current_index)
        organisation_document_link_language.document_link = model

        self.document_link_language_current_index = self.register_model(
            'OrganisationDocumentLinkLanguage',
            organisation_document_link_language)

        # store element
        return element

    def iati_organisations__iati_organisation__document_link__document_date(
            self, element):
        """attributes:
        format:application/vnd.oasis.opendocument.text
        url:http:www.example.org/docs/report_en.odt

        tag:document-link"""
        iso_date = element.attrib.get('iso-date')

        if not iso_date:
            raise RequiredFieldError(
                "document-link/document-date",
                "iso-date",
                "required attribute missing")

        iso_date = self.validate_date(iso_date)

        if not iso_date:
            raise FieldValidationError(
                "document-link/document-date",
                "iso-date",
                "iso-date not of type xsd:date")

        document_link = self.get_model(
            'OrganisationDocumentLink',
            self.organisation_document_link_current_index)

        document_link.iso_date = iso_date
        return element

    def iati_organisations__iati_organisation__document_link__recipient_country(  # NOQA: E501
            self, element):
        """atributes:
        code:AF

        tag:recipient-country"""
        model = self.get_model('OrganisationDocumentLink',
                               self.organisation_document_link_current_index)

        country = self.get_or_none(Country, code=element.attrib.get('code'))

        document_link_recipient_country = DocumentLinkRecipientCountry()
        document_link_recipient_country.recipient_country = country
        document_link_recipient_country.document_link = model

        self.register_model('DocumentLinkRecipientCountry',
                            document_link_recipient_country)

        # store element
        return element

    def post_save_models(self):
        """Perform all actions that need to happen after a single
        organisation's been parsed."""
        organisation = self.get_model('Organisation')

        if not organisation:
            return False

        post_save.set_activity_reporting_organisation(organisation)
        post_save.set_publisher_fk(organisation)

        # Solr indexing
        OrganisationTaskIndexing(instance=organisation).run()

    def post_save_file(self, xml_source, files_to_keep):
        pass

    def post_save_validators(self, dataset):
        pass
