from systems.plugins.index import BaseProvider
from utility.sam import SAMAPI


class Provider(BaseProvider('source', 'sam_entities')):

    def load_items(self, context):
        for entity in SAMAPI(self.command).load_entities():
            yield entity


    def load_item(self, response, context):
        return {
            'entity': response.export()
        }
