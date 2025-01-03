from django.conf import settings

from .request import request_legacy_session
from .data import Collection, RecursiveCollection, load_json, dump_json, get_identifier
from .filesystem import filesystem_dir
from .time import Time

import os
import urllib
import requests
import pandas
import json
import time
import re


def parse_description(command, notice):
    webpage = command.parse_webpage(notice.web_url)
    if webpage.url == 'https://sam.gov/404':
        raise SAMNoticeMissingError("SAM webpage does not exist")

    description = webpage.soup.find('div', class_ = 'inner-html-description')

    if description:
        description.attrs = {}
        description['class'] = "notice-description"

    description_text = description.get_text(separator = "\n\n", strip = True) if description else ''
    description_html = description.prettify() if description else ''

    return description_text, description_html


class SAMAPIError(Exception):
    pass

class SAMNoticeMissingError(Exception):
    pass


class SAMAPI(object):

    def __init__(self, command):
        self.command = command

        self.opportunity_url = "https://api.sam.gov/opportunities/v2/search?api_key={}".format(settings.SAM_API_KEY)
        self.organization_url = "https://api.sam.gov/prod/federalorganizations/v1/orgs?api_key={}".format(settings.SAM_API_KEY)

        self.request_time = Time(date_format = '%m/%d/%Y')
        self.tz_response_time = Time(
            date_format = "%Y-%m-%d",
            time_format = "%H:%M:%S%z",
            spacer = 'T'
        )
        self.response_time = Time(
            date_format = "%Y-%m-%d",
            time_format = "%H:%M:%S",
            spacer = 'T'
        )
        self.entity_date = Time(date_format = "%Y%m%d")


    def load_opportunities(self,
        params = None,
        limit = 1000,
        offset = 0,
        next_callback = None,
        complete_callback = None
    ):
        count = None

        if not params:
            params = {}

        if 'ptype' not in params or params['ptype'] not in ['p', 'r', 'o', 'k']:
            params['ptype'] = 'p,r,o,k'

        while count is None or count == limit:
            data = self.get_opportunity_page({ **params, 'limit': limit, 'offset': offset })
            count = len(data)

            for notice in data:
                try:
                    notice['fullParentPathCode'] = re.split(r'\s*\.\s*', notice['fullParentPathCode'])
                    notice['fullParentPathName'] = re.split(r'\s*\.\s*', notice['fullParentPathName'])

                    notice['postedDate'] = self.response_time.to_datetime(notice['postedDate']) if notice['postedDate'] else None
                    notice['archiveDate'] = self.response_time.to_datetime(notice['archiveDate']) if notice['archiveDate'] else None

                    try:
                        notice['responseDeadLine'] = self.tz_response_time.to_datetime(notice['responseDeadLine']) if notice['responseDeadLine'] else None
                    except Exception as e:
                        notice['responseDeadLine'] = self.response_time.to_datetime(notice['responseDeadLine'])

                    notice['descriptionUrl'] = notice['description']
                    yield RecursiveCollection(**notice)

                except Exception as e:
                    self.command.warning("SAM notice parse failed with: {}: {}".format(e, dump_json(notice, indent = 2)))

            offset = offset + count

            if next_callback and callable(next_callback):
                next_callback(offset)

            time.sleep(2)

        if complete_callback and callable(complete_callback):
            complete_callback()


    def get_opportunity_page(self, params):
        if 'postedFrom' in params:
            params['postedFrom'] = self.request_time.to_date_string(params['postedFrom'])
        else:
            params['postedFrom'] = self.request_time.to_date_string(self.request_time.shift(self.request_time.now, -364))

        if 'postedTo' in params:
            params['postedTo'] = self.request_time.to_date_string(params['postedTo'])
        else:
            params['postedTo'] = self.request_time.now_date_string

        if 'rdlfrom' in params:
            params['rdlfrom'] = self.request_time.to_date_string(params['rdlfrom'])
        if 'rdlto' in params:
            params['rdlto'] = self.request_time.to_date_string(params['rdlto'])

        if 'limit' not in params:
            params['limit'] = 1
        if 'offset' not in params:
            params['offset'] = 0

        url = "{}&{}".format(self.opportunity_url, urllib.parse.urlencode(params))

        self.command.data('SAM opportunity search', url)
        response = request_legacy_session().get(url)
        data = load_json(response.text)

        if response.status_code == 200:
            return data['opportunitiesData']
        else:
            if 'error' in data:
                message = data['error']['message']
            else:
                message = data['errorMessage']

            raise SAMAPIError("SAM Request failed with {} - {}: {}".format(response.status_code, message, url))


    def load_organizations(self,
        params = None,
        offset = 0,
        next_callback = None,
        complete_callback = None
    ):
        limit = 100
        count = None

        if params is None:
            params = {}

        while count is None or count == limit:
            data = self.get_organization_page({ **params, 'offset': offset, 'limit': limit })
            count = len(data)

            for organization in data:
                if organization['fhorgid'] == organization['fhdeptindagencyorgid']:
                    organization['fhdeptindagencyorgid'] = None

                yield RecursiveCollection(**organization)

            offset = offset + count

            if next_callback and callable(next_callback):
                next_callback(offset)

            time.sleep(1)

        if complete_callback and callable(complete_callback):
            complete_callback()

    def get_organization_page(self, params):
        params['status'] = 'Active'

        if 'offset' not in params:
            params['offset'] = 0

        url = "{}&{}".format(self.organization_url, urllib.parse.urlencode(params))

        self.command.data('SAM organizations', url)
        response = request_legacy_session().get(url)
        data = load_json(response.text)

        if response.status_code == 200:
            return data['orglist']
        else:
            if 'error' in data:
                message = data['error']['message']
            else:
                message = data['errorMessage']

            raise SAMAPIError("SAM Request failed with {} - {}: {}".format(response.status_code, message, url))


    def load_entities(self):
        with filesystem_dir(self.command.manager.sam_entity_path) as filesystem:
            file_data = filesystem.load('entities.dat')
            for entity in file_data.split("\n")[1:-1]:
                field_values = entity.removesuffix('!end').split('|')

                naics = [
                    naics.removesuffix('Y').removesuffix('N').removesuffix('E')
                    for naics in field_values[34].split('~')
                ] if field_values[34] else []

                if field_values[32] in naics:
                    naics.remove(field_values[32])
                    naics = [field_values[32]] + naics

                self.command.data('Importing', field_values[0])
                yield Collection(**{
                    'uei': field_values[0],
                    'cage': field_values[3],
                    'start_date': self.entity_date.to_datetime(field_values[24]) if field_values[24] else None,
                    'registration_date': self.entity_date.to_datetime(field_values[7]) if field_values[7] else None,
                    'expiration_date': self.entity_date.to_datetime(field_values[8]) if field_values[8] else None,
                    'last_update_date': self.entity_date.to_datetime(field_values[9]) if field_values[9] else None,
                    'activation_date': self.entity_date.to_datetime(field_values[10]) if field_values[10] else None,
                    'name': field_values[11],
                    'dba_name': field_values[12],
                    'structure': field_values[27],
                    'types': field_values[31].split('~') if field_values[31] else [],
                    'address_line1': field_values[15],
                    'address_line2': field_values[16],
                    'address_city': field_values[17],
                    'address_province': field_values[18],
                    'address_zipcode': field_values[19],
                    'address_country': field_values[21],
                    'incorporation_province': field_values[28],
                    'incorporation_country': field_values[29],
                    'url': field_values[26],
                    'naics': naics,
                    'psc': field_values[36].split('~') if field_values[36] else [],
                })
