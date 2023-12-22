from systems.plugins.index import BaseProvider
from utility.sam import SAMAPI
from utility.data import prioritize


class Provider(BaseProvider('source', 'sam_organizations')):

    def load_items(self, context):
        organizations = {}

        for organization in SAMAPI(self.command).load_organizations(self.field_params):
            organizations[organization.fhorgid] = organization.export()

        for priority, org_ids in prioritize(organizations, keep_requires = True, requires_field = 'fhdeptindagencyorgid').items():
            for org_id in sorted(org_ids):
                yield organizations[org_id]


    def load_item(self, response, context):
        return {
            'organization': {
                'id': response['fhorgid'],
                'name': response['fhorgname'],
                'parent_id': response['fhdeptindagencyorgid'],
                'parent_name': response['fhagencyorgname'],
                'type': response['fhorgtype'],
                'code': response['agencycode']
            }
        }
