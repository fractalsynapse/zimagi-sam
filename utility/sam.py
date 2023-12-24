from django.conf import settings
from bs4 import BeautifulSoup

from .request import request_legacy_session
from .data import Collection, RecursiveCollection, load_json, get_identifier
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
    html_page = command.submit('agent:browser', notice.web_url)
    description = BeautifulSoup(html_page, 'html.parser').find('div', class_ = 'inner-html-description')

    if description:
        description.attrs = {}
        description['class'] = "notice-description"

    description_text = description.get_text(separator = "\n\n", strip = True) if description else ''
    description_html = description.prettify() if description else ''

    return description_text, description_html


class SAMAPIError(Exception):
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

        with filesystem_dir(os.path.join(self.command.manager.sam_cache_path, 'search')) as filesystem:
            url = "{}&{}".format(self.opportunity_url, urllib.parse.urlencode(params))
            cache_key = "{}.json".format(get_identifier(url))
            response_text = filesystem.load(cache_key)
            status_code = 200

            if not response_text:
                self.command.data('SAM opportunity search', url)

                response = request_legacy_session().get(url)
                response_text = response.text
                status_code = response.status_code

                if status_code == 200:
                    filesystem.save(response_text, cache_key)
            else:
                self.command.data('SAM cached opportunity search', url)

        data = load_json(response_text)

        if status_code == 200:
            return data['opportunitiesData']
        else:
            if 'error' in data:
                message = data['error']['message']
            else:
                message = data['errorMessage']

            raise SAMAPIError("SAM Request failed with {} - {}: {}".format(status_code, message, url))


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

        with filesystem_dir(os.path.join(self.command.manager.sam_cache_path, 'orgs')) as filesystem:
            url = "{}&{}".format(self.organization_url, urllib.parse.urlencode(params))
            cache_key = "{}.json".format(get_identifier(url))
            response_text = filesystem.load(cache_key)
            status_code = 200

            if not response_text:
                self.command.data('SAM organizations', url)

                response = request_legacy_session().get(url)
                response_text = response.text
                status_code = response.status_code

                if status_code == 200:
                    filesystem.save(response_text, cache_key)
            else:
                self.command.data('SAM cached organizations', url)

        data = load_json(response_text)

        if status_code == 200:
            return data['orglist']
        else:
            if 'error' in data:
                message = data['error']['message']
            else:
                message = data['errorMessage']

            raise SAMAPIError("SAM Request failed with {} - {}: {}".format(status_code, message, url))


    def load_entities(self):
        with filesystem_dir(self.command.manager.sam_entity_path) as filesystem:
            file_data = filesystem.load('entities.dat')
            for entity in file_data.split("\n"):
                field_values = entity.removesuffix('!end').split('|')

                naics = [
                    naics.removesuffix('Y').removesuffix('N').removesuffix('E')
                    for naics in field_values[34].split('~')
                ] if field_values[34] else []

                if field_values[32] in naics:
                    naics.remove(field_values[32])
                    naics = [field_values[32]] + naics

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
