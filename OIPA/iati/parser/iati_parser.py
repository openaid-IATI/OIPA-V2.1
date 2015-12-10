from IATI_2_01 import Parse as IATI_201_Parser
from IATI_1_05 import Parse as IATI_105_Parser
from IATI_1_03 import Parse as IATI_103_Parser
from iati_organisation.organisation_2_01 import Parse as Org_2_01_Parser
from iati_organisation.organisation_1_05 import Parse as Org_1_05_Parser
from iati.filegrabber import FileGrabber
from lxml import etree
from iati_synchroniser.exception_handler import exception_handler
from django import db
from django.conf import settings


class ParseIATI():
    def __init__(self, source, root=None):
        """
        Given a source IATI file, prepare an IATI parser
        """

        self.source = source
        self.url = source.source_url
        self.xml_source_ref = source.ref
        
        if root is not None:
            self.root = root
            self.parser = self._prepare_parser(self.root, source)
            return

        file_grabber = FileGrabber()
        response = file_grabber.get_the_file(self.url)

        if (not response or response.code != 200):
            # TODO: add error code to log - 2015-12-09
            raise ValueError("source url {} down or doesn't exist, error code".format(self.url))

        iati_file = response.read()

        self.root = etree.fromstring(str(iati_file))
        self.parser = self._prepare_parser(self.root, source)

    def _prepare_parser(self, root, source):
        """
            Prepares the parser, given the lxml activity file root
        """

        iati_version = root.xpath('@version')

        if len(iati_version) > 0:
            iati_version = iati_version[0]
        if source.type == 1:
            if iati_version == '2.01':
                parser = IATI_201_Parser(root)
            elif iati_version == '1.03':
                parser = IATI_103_Parser(root)
                parser.VERSION = iati_version
            else:
                parser = IATI_105_Parser(root)
                parser.VERSION = '1.05'
        elif source.type == 2:
            #organisation file
            if iati_version == '2.01':
                parser = Org_2_01_Parser(root)
                parser.VERSION = iati_version
            else:
                parser = Org_1_05_Parser(root)
        
        parser.iati_source = source

        return parser

    def get_parser(self):
        return self.parser

    def parse_all(self):
        """
        Parse all activities 
        """

        # TODO: do removal here - 2015-12-10

        self.parser.load_and_parse(self.root)

        # Throw away query logs when in debug mode to prevent memory from overflowing
        if settings.DEBUG:
            db.reset_queries()

    def parse_activity(self, activity_id):
        """
        Parse only one activity with {activity_id}
        """

        try:
            (activity,) = self.root.xpath('//iati-activity/iati-identifier[text()="{}"]'.format(activity_id))
        except ValueError:
            raise ValueError("Activity {} doesn't exist in {}".format(activity_id, self.url))
        
        self.parser.parse(activity.getparent())
        self.parser.save_all_models()

